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
