from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class ToolParameterSpec:
    name: str
    param_type: str = "string"
    required: bool = False
    description: str = ""
    default: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "param_type": self.param_type,
            "required": self.required,
            "description": self.description,
            "default": self.default,
        }


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: list[ToolParameterSpec] = field(default_factory=list)
    returns: str = "text"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": [item.to_dict() for item in self.parameters],
            "returns": self.returns,
        }


@dataclass(slots=True)
class ToolCall:
    tool_name: str
    args: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    agent_id: str = "main"
    caller: str = "agent"
    require_confirmation: bool = False
    confirm: bool = False


@dataclass(slots=True)
class ToolResult:
    success: bool
    content: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolExecutionRecord:
    execution_id: str
    timestamp: datetime
    tool_name: str
    session_id: str
    agent_id: str
    caller: str
    args: dict[str, Any]
    success: bool
    latency_ms: float
    result_preview: str
    denied_reason: str | None = None

    @classmethod
    def create(
        cls,
        *,
        tool_name: str,
        session_id: str,
        agent_id: str,
        caller: str,
        args: dict[str, Any],
        success: bool,
        latency_ms: float,
        result_preview: str,
        denied_reason: str | None = None,
    ) -> "ToolExecutionRecord":
        return cls(
            execution_id=str(uuid4()),
            timestamp=_utc_now(),
            tool_name=tool_name,
            session_id=session_id,
            agent_id=agent_id,
            caller=caller,
            args=args,
            success=success,
            latency_ms=latency_ms,
            result_preview=result_preview,
            denied_reason=denied_reason,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "timestamp": self.timestamp.isoformat(),
            "tool_name": self.tool_name,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "caller": self.caller,
            "args": self.args,
            "success": self.success,
            "latency_ms": self.latency_ms,
            "result_preview": self.result_preview,
            "denied_reason": self.denied_reason,
        }


class Tool(Protocol):
    spec: ToolSpec

    async def run(self, **kwargs: Any) -> ToolResult:
        ...
