from __future__ import annotations

from dataclasses import dataclass, field

from app.agent.planner import TurnPlan
from app.agent.response_generator import ResponseGenerator
from app.tools.executor import ToolExecutor


@dataclass(slots=True)
class LoopResult:
    response: str
    tool_outputs: list[str] = field(default_factory=list)


class AgentLoop:
    def __init__(self, tool_executor: ToolExecutor, response_generator: ResponseGenerator) -> None:
        self._tool_executor = tool_executor
        self._response_generator = response_generator

    async def run(self, plan: TurnPlan, user_message: str) -> LoopResult:
        tool_outputs: list[str] = []

        for tool_call in plan.tool_calls:
            result = await self._tool_executor.execute(tool_call.name, **tool_call.args)
            tool_outputs.append(f"{tool_call.name}: {result.content}")

        reply = self._response_generator.generate(user_message, tool_outputs)
        return LoopResult(response=reply, tool_outputs=tool_outputs)
