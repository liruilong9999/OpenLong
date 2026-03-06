from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from app.models.message import ChatMessage


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SessionStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    EXPIRED = "expired"


@dataclass(slots=True)
class SessionRecord:
    session_id: str
    agent_id: str
    status: SessionStatus = SessionStatus.ACTIVE
    messages: list[ChatMessage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    closed_at: datetime | None = None

    def touch(self) -> None:
        self.updated_at = _utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "status": self.status.value,
            "messages": [item.to_dict() for item in self.messages],
            "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SessionRecord":
        status_value = str(payload.get("status") or SessionStatus.ACTIVE.value)
        created_at_value = payload.get("created_at")
        updated_at_value = payload.get("updated_at")
        closed_at_value = payload.get("closed_at")
        return cls(
            session_id=str(payload.get("session_id") or ""),
            agent_id=str(payload.get("agent_id") or "main"),
            status=SessionStatus(status_value),
            messages=[ChatMessage.from_dict(item) for item in list(payload.get("messages") or [])],
            metadata=dict(payload.get("metadata") or {}),
            created_at=datetime.fromisoformat(str(created_at_value)) if created_at_value else _utc_now(),
            updated_at=datetime.fromisoformat(str(updated_at_value)) if updated_at_value else _utc_now(),
            closed_at=datetime.fromisoformat(str(closed_at_value)) if closed_at_value else None,
        )
