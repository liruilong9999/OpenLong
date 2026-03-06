from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(slots=True)
class ChatMessage:
    role: Role
    content: str
    attachments: list[dict[str, Any]] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_prompt_line(self) -> str:
        if not self.attachments:
            return f"[{self.role.value}] {self.content}"

        attachment_text = ", ".join(
            str(item.get("filename") or item.get("saved_name") or item.get("relative_path") or "attachment")
            for item in self.attachments
        )
        return f"[{self.role.value}] {self.content} [attachments: {attachment_text}]"

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "content": self.content,
            "attachments": list(self.attachments),
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChatMessage":
        role_value = str(payload.get("role") or Role.USER.value)
        timestamp_value = payload.get("timestamp")
        timestamp = datetime.fromisoformat(str(timestamp_value)) if timestamp_value else datetime.now(timezone.utc)
        return cls(
            role=Role(role_value),
            content=str(payload.get("content") or ""),
            attachments=list(payload.get("attachments") or []),
            timestamp=timestamp,
        )
