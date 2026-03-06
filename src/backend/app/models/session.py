from __future__ import annotations

from dataclasses import dataclass, field

from app.models.message import ChatMessage


@dataclass(slots=True)
class SessionRecord:
    session_id: str
    agent_id: str
    messages: list[ChatMessage] = field(default_factory=list)
