from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ToolIntent:
    name: str
    args: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class TurnPlan:
    objective: str
    tool_calls: list[ToolIntent] = field(default_factory=list)


class Planner:
    def plan(self, user_message: str) -> TurnPlan:
        if user_message.startswith("/tool "):
            parts = user_message.split(maxsplit=2)
            tool_name = parts[1] if len(parts) > 1 else ""
            tool_payload = parts[2] if len(parts) > 2 else ""
            return TurnPlan(
                objective="execute explicit tool request",
                tool_calls=[ToolIntent(name=tool_name, args={"input": tool_payload})],
            )

        return TurnPlan(objective="answer user request")
