from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

from app.models.message import ChatMessage
from app.models.session import SessionRecord, SessionStatus


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SessionManager:
    def __init__(self, ttl_seconds: int = 24 * 3600) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._ttl_seconds = ttl_seconds
        self._lock = Lock()

    def create_session(
        self,
        session_id: str,
        agent_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> SessionRecord:
        with self._lock:
            record = self._sessions.get(session_id)
            if record is not None:
                return record

            record = SessionRecord(session_id=session_id, agent_id=agent_id, metadata=metadata or {})
            self._sessions[session_id] = record
            return record

    def get_or_create(self, session_id: str, agent_id: str = "main") -> SessionRecord:
        return self.create_session(session_id=session_id, agent_id=agent_id)

    def get(self, session_id: str) -> SessionRecord | None:
        with self._lock:
            return self._sessions.get(session_id)

    def assign_agent(self, session_id: str, agent_id: str) -> SessionRecord:
        with self._lock:
            session = self._sessions[session_id]
            session.agent_id = agent_id
            session.touch()
            return session

    def append_message(self, session_id: str, message: ChatMessage) -> None:
        with self._lock:
            session = self._sessions[session_id]
            session.messages.append(message)
            session.touch()

    def close_session(self, session_id: str, reason: str = "manual") -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False

            if session.status == SessionStatus.CLOSED:
                return True

            session.status = SessionStatus.CLOSED
            session.closed_at = _utc_now()
            session.metadata["close_reason"] = reason
            session.touch()
            return True

    def expire_inactive(self) -> list[str]:
        now = _utc_now()
        expired_ids: list[str] = []

        with self._lock:
            for session in self._sessions.values():
                if session.status != SessionStatus.ACTIVE:
                    continue

                if now - session.updated_at > timedelta(seconds=self._ttl_seconds):
                    session.status = SessionStatus.EXPIRED
                    session.closed_at = now
                    session.touch()
                    expired_ids.append(session.session_id)

        return expired_ids

    def get_history(self, session_id: str, limit: int = 100) -> list[dict[str, str]]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return []

            return [
                {
                    "role": item.role.value,
                    "content": item.content,
                    "timestamp": item.timestamp.isoformat(),
                    "attachments": item.attachments,
                }
                for item in session.messages[-limit:]
            ]

    def get_session_snapshot(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None

            return {
                "session_id": session.session_id,
                "agent_id": session.agent_id,
                "status": session.status.value,
                "message_count": len(session.messages),
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "closed_at": session.closed_at.isoformat() if session.closed_at else None,
                "metadata": session.metadata,
            }

    def list_sessions(self, include_closed: bool = True) -> list[dict[str, Any]]:
        with self._lock:
            sessions = list(self._sessions.values())

        items: list[dict[str, Any]] = []
        for session in sessions:
            if not include_closed and session.status != SessionStatus.ACTIVE:
                continue

            items.append(
                {
                    "session_id": session.session_id,
                    "agent_id": session.agent_id,
                    "status": session.status.value,
                    "message_count": len(session.messages),
                    "created_at": session.created_at.isoformat(),
                    "updated_at": session.updated_at.isoformat(),
                    "closed_at": session.closed_at.isoformat() if session.closed_at else None,
                }
            )

        items.sort(key=lambda item: item["updated_at"], reverse=True)
        return items

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for item in self._sessions.values() if item.status == SessionStatus.ACTIVE)
