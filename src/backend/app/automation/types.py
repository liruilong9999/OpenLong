from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AutomationSessionTarget(str, Enum):
    ISOLATED = "isolated"
    SHARED = "shared"


class AutomationDeliveryMode(str, Enum):
    NONE = "none"
    WEBHOOK = "webhook"


class AutomationRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(slots=True)
class AutomationJob:
    job_id: str
    name: str
    agent_id: str
    prompt: str
    cron: str
    enabled: bool = True
    session_target: AutomationSessionTarget = AutomationSessionTarget.ISOLATED
    delivery_mode: AutomationDeliveryMode = AutomationDeliveryMode.NONE
    delivery_to: str = ""
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "name": self.name,
            "agent_id": self.agent_id,
            "prompt": self.prompt,
            "cron": self.cron,
            "enabled": self.enabled,
            "session_target": self.session_target.value,
            "delivery_mode": self.delivery_mode.value,
            "delivery_to": self.delivery_to,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AutomationJob":
        return cls(
            job_id=str(payload.get("job_id") or str(uuid4())),
            name=str(payload.get("name") or "unnamed-job"),
            agent_id=str(payload.get("agent_id") or "main"),
            prompt=str(payload.get("prompt") or ""),
            cron=str(payload.get("cron") or "* * * * *"),
            enabled=bool(payload.get("enabled", True)),
            session_target=AutomationSessionTarget(str(payload.get("session_target") or AutomationSessionTarget.ISOLATED.value)),
            delivery_mode=AutomationDeliveryMode(str(payload.get("delivery_mode") or AutomationDeliveryMode.NONE.value)),
            delivery_to=str(payload.get("delivery_to") or ""),
            created_at=_parse_datetime(payload.get("created_at")) or _utc_now(),
            updated_at=_parse_datetime(payload.get("updated_at")) or _utc_now(),
            last_run_at=_parse_datetime(payload.get("last_run_at")),
            next_run_at=_parse_datetime(payload.get("next_run_at")),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(slots=True)
class AutomationRun:
    run_id: str
    job_id: str
    agent_id: str
    session_id: str
    status: AutomationRunStatus = AutomationRunStatus.PENDING
    delivery_mode: AutomationDeliveryMode = AutomationDeliveryMode.NONE
    delivery_to: str = ""
    task_id: str = ""
    created_at: datetime = field(default_factory=_utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "job_id": self.job_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "status": self.status.value,
            "delivery_mode": self.delivery_mode.value,
            "delivery_to": self.delivery_to,
            "task_id": self.task_id,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "result": self.result,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AutomationRun":
        return cls(
            run_id=str(payload.get("run_id") or str(uuid4())),
            job_id=str(payload.get("job_id") or ""),
            agent_id=str(payload.get("agent_id") or "main"),
            session_id=str(payload.get("session_id") or ""),
            status=AutomationRunStatus(str(payload.get("status") or AutomationRunStatus.PENDING.value)),
            delivery_mode=AutomationDeliveryMode(str(payload.get("delivery_mode") or AutomationDeliveryMode.NONE.value)),
            delivery_to=str(payload.get("delivery_to") or ""),
            task_id=str(payload.get("task_id") or ""),
            created_at=_parse_datetime(payload.get("created_at")) or _utc_now(),
            started_at=_parse_datetime(payload.get("started_at")),
            finished_at=_parse_datetime(payload.get("finished_at")),
            result=dict(payload.get("result") or {}),
            error=str(payload.get("error")) if payload.get("error") else None,
        )


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
