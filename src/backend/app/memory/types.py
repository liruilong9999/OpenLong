from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryType(str, Enum):
    USER_INFO = "user_info"
    TASK_RESULT = "task_result"
    AGENT_SUMMARY = "agent_summary"
    TOOL_RESULT = "tool_result"
    FACT = "fact"
    CONVERSATION = "conversation"


@dataclass(slots=True)
class MemoryEntry:
    memory_id: str
    timestamp: datetime
    memory_type: MemoryType
    content: str
    importance: float
    source: str
    session_id: str
    weight: float
    access_count: int = 0
    last_accessed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        memory_type: MemoryType,
        content: str,
        source: str,
        session_id: str,
        importance: float,
        metadata: dict[str, Any] | None = None,
    ) -> "MemoryEntry":
        value = _clamp(importance)
        return cls(
            memory_id=str(uuid4()),
            timestamp=_utc_now(),
            memory_type=memory_type,
            content=content.strip(),
            importance=value,
            source=source,
            session_id=session_id,
            weight=value,
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "timestamp": self.timestamp.isoformat(),
            "memory_type": self.memory_type.value,
            "content": self.content,
            "importance": self.importance,
            "source": self.source,
            "session_id": self.session_id,
            "weight": self.weight,
            "access_count": self.access_count,
            "last_accessed_at": self.last_accessed_at.isoformat() if self.last_accessed_at else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MemoryEntry":
        timestamp = payload.get("timestamp")
        last_accessed = payload.get("last_accessed_at")

        return cls(
            memory_id=str(payload.get("memory_id") or str(uuid4())),
            timestamp=_parse_datetime(timestamp),
            memory_type=MemoryType(str(payload.get("memory_type", MemoryType.CONVERSATION.value))),
            content=str(payload.get("content", "")),
            importance=_clamp(float(payload.get("importance", 0.5))),
            source=str(payload.get("source", "unknown")),
            session_id=str(payload.get("session_id", "")),
            weight=_clamp(float(payload.get("weight", payload.get("importance", 0.5)))),
            access_count=int(payload.get("access_count", 0)),
            last_accessed_at=_parse_datetime(last_accessed) if last_accessed else None,
            metadata=dict(payload.get("metadata", {}) or {}),
        )


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    return _utc_now()


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value
