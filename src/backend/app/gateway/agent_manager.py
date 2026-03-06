from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Any

from app.agent.runtime import AgentRuntime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass(slots=True)
class AgentRecord:
    agent_id: str
    status: AgentStatus = AgentStatus.RUNNING
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    last_error: str | None = None
    session_ids: set[str] = field(default_factory=set)

    def touch(self) -> None:
        self.updated_at = _utc_now()


class AgentManager:
    def __init__(self, runtime: AgentRuntime) -> None:
        self._runtime = runtime
        self._agents: dict[str, AgentRecord] = {}
        self._lock = Lock()
        self.create_agent("main")

    def create_agent(self, agent_id: str) -> AgentRecord:
        with self._lock:
            record = self._agents.get(agent_id)
            if record is None:
                self._runtime.get_or_create(agent_id)
                record = AgentRecord(agent_id=agent_id)
                self._agents[agent_id] = record
            else:
                if record.status != AgentStatus.RUNNING:
                    self._runtime.get_or_create(agent_id)
                record.status = AgentStatus.RUNNING
                record.last_error = None
                record.touch()
            return record

    def ensure_agent(self, agent_id: str) -> AgentRecord:
        return self.create_agent(agent_id)

    def stop_agent(self, agent_id: str, force: bool = False) -> tuple[bool, str]:
        with self._lock:
            record = self._agents.get(agent_id)
            if record is None:
                return False, f"agent not found: {agent_id}"

            if agent_id == "main" and not force:
                return False, "main agent cannot be stopped unless force=true"

            if record.session_ids and not force:
                return False, "agent has active sessions, pass force=true to stop"

            record.status = AgentStatus.STOPPED
            record.touch()
            record.last_error = None
            session_ids = list(record.session_ids)
            record.session_ids.clear()

        if agent_id != "main":
            self._runtime.remove(agent_id)

        # 强制停止时，调用方应重新分配这些会话。
        if session_ids:
            self.create_agent("main")

        return True, "stopped"

    def mark_error(self, agent_id: str, error_message: str) -> None:
        with self._lock:
            record = self._agents.get(agent_id)
            if record is None:
                record = AgentRecord(agent_id=agent_id)
                self._agents[agent_id] = record
            record.status = AgentStatus.ERROR
            record.last_error = error_message
            record.touch()

    def is_running(self, agent_id: str) -> bool:
        with self._lock:
            record = self._agents.get(agent_id)
            return bool(record and record.status == AgentStatus.RUNNING)

    def assign_session(self, session_id: str, preferred_agent_id: str | None = None) -> str:
        if preferred_agent_id:
            record = self.create_agent(preferred_agent_id)
            with self._lock:
                record.session_ids.add(session_id)
                record.touch()
            return preferred_agent_id

        with self._lock:
            candidates = [item for item in self._agents.values() if item.status == AgentStatus.RUNNING]
            chosen = min(candidates, key=lambda item: len(item.session_ids)) if candidates else None

        if chosen is None:
            chosen = self.create_agent("main")

        with self._lock:
            chosen.session_ids.add(session_id)
            chosen.touch()
            return chosen.agent_id

    def release_session(self, session_id: str) -> None:
        with self._lock:
            for record in self._agents.values():
                if session_id in record.session_ids:
                    record.session_ids.remove(session_id)
                    record.touch()

    def reassign_session(self, session_id: str, new_agent_id: str) -> str:
        self.release_session(session_id)
        return self.assign_session(session_id=session_id, preferred_agent_id=new_agent_id)

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._agents.get(agent_id)
            if record is None:
                return None

            return {
                "agent_id": record.agent_id,
                "status": record.status.value,
                "active_sessions": len(record.session_ids),
                "created_at": record.created_at.isoformat(),
                "updated_at": record.updated_at.isoformat(),
                "last_error": record.last_error,
            }

    def list_agents(self, include_stopped: bool = True) -> list[dict[str, Any]]:
        with self._lock:
            records = list(self._agents.values())

        items: list[dict[str, Any]] = []
        for record in records:
            if not include_stopped and record.status != AgentStatus.RUNNING:
                continue

            items.append(
                {
                    "agent_id": record.agent_id,
                    "status": record.status.value,
                    "active_sessions": len(record.session_ids),
                    "created_at": record.created_at.isoformat(),
                    "updated_at": record.updated_at.isoformat(),
                    "last_error": record.last_error,
                }
            )

        items.sort(key=lambda item: item["agent_id"])
        return items
