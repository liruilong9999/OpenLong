from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentTaskStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class AgentTask:
    task_id: str
    input_text: str
    status: AgentTaskStatus = AgentTaskStatus.RUNNING
    started_at: datetime = field(default_factory=_utc_now)
    finished_at: datetime | None = None
    error: str | None = None


@dataclass(slots=True)
class Agent:
    agent_id: str
    agent_type: str
    workspace: Path
    memory: dict[str, Any] = field(default_factory=dict)
    skills: list[str] = field(default_factory=list)
    current_task: AgentTask | None = None


@dataclass(slots=True)
class ModelOutput:
    text: str
    confidence: float = 0.5
    should_call_tool: bool = False
    should_continue: bool = False
    tool_hint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass(slots=True)
class ToolCallTrace:
    call: ToolCall
    success: bool
    content: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentTurnResult:
    reply: str
    tool_outputs: list[str] = field(default_factory=list)
    memory_entries: list[str] = field(default_factory=list)
    model_outputs: list[str] = field(default_factory=list)
    iterations: int = 1
