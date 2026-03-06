from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(slots=True)
class ChatMessage:
    role: Role
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_prompt_line(self) -> str:
        return f"[{self.role.value}] {self.content}"
