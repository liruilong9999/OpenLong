from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from app.agent.model_client import ModelClient, ModelRequest
from app.agent.planner import Planner, TurnPlan
from app.agent.prompt_builder import PromptBuilder
from app.agent.response_generator import ResponseGenerator
from app.agent.types import Agent, ModelOutput, ToolCallTrace
from app.models.message import ChatMessage
from app.skills.types import SkillSpec
from app.tools.executor import ToolExecutor


_USER_FACT_PATTERNS = [
    re.compile(r"我叫\s*([\u4e00-\u9fa5A-Za-z0-9_\-]{1,32})"),
    re.compile(r"我的名字是\s*([\u4e00-\u9fa5A-Za-z0-9_\-]{1,32})"),
    re.compile(r"I\s+am\s+([A-Za-z][A-Za-z0-9_\-]{0,31})", flags=re.IGNORECASE),
]


@dataclass(slots=True)
class LoopResult:
    response: str
    tool_traces: list[ToolCallTrace] = field(default_factory=list)
    model_outputs: list[ModelOutput] = field(default_factory=list)
    memory_entries: list[str] = field(default_factory=list)
    plans: list[TurnPlan] = field(default_factory=list)


class AgentLoop:
    def __init__(
        self,
        *,
        tool_executor: ToolExecutor,
        prompt_builder: PromptBuilder,
        planner: Planner,
        model_client: ModelClient,
        response_generator: ResponseGenerator,
        max_iterations: int = 3,
    ) -> None:
        self._tool_executor = tool_executor
        self._prompt_builder = prompt_builder
        self._planner = planner
        self._model_client = model_client
        self._response_generator = response_generator
        self._max_iterations = max_iterations

    async def run(
        self,
        *,
        agent: Agent,
        session_id: str,
        task_type: str,
        user_message: str,
        attachments: list[dict[str, object]] | None,
        history: list[ChatMessage],
        context_block: str,
        memories: list[str],
        skills: list[SkillSpec],
        matched_skills: list[SkillSpec],
        task_id: str,
        model_routes: list[dict[str, Any]] | None = None,
        model_route_source: str = "default",
        attempt_observer: Any = None,
    ) -> LoopResult:
        scratchpad_lines: list[str] = []
        tool_traces: list[ToolCallTrace] = []
        model_outputs: list[ModelOutput] = []
        plans: list[TurnPlan] = []

        for iteration in range(self._max_iterations):
            prompt_bundle = self._prompt_builder.build(
                context_block=context_block,
                history=history,
                memories=memories,
                skills=skills,
                matched_skills=matched_skills,
                user_message=user_message,
                attachments=attachments or [],
                scratchpad="\n".join(scratchpad_lines),
            )

            model_output = await self._model_client.generate(
                ModelRequest(
                    agent_id=agent.agent_id,
                    task_id=task_id,
                    user_message=user_message,
                    prompt=prompt_bundle.full_prompt,
                    iteration=iteration,
                    task_type=task_type,
                    tool_summaries=[trace.content[:240] for trace in tool_traces],
                    attachments=list(attachments or []),
                    model_routes=list(model_routes or []),
                    model_route_source=model_route_source,
                    attempt_observer=attempt_observer,
                )
            )
            model_outputs.append(model_output)

            plan = self._planner.plan(
                user_message=user_message,
                model_output=model_output,
                iteration=iteration,
                tool_traces=tool_traces,
            )
            plans.append(plan)

            for tool_call in plan.tool_calls:
                result = await self._tool_executor.execute(
                    tool_call.name,
                    session_id=session_id,
                    agent_id=agent.agent_id,
                    **tool_call.args,
                )
                trace = ToolCallTrace(
                    call=tool_call,
                    success=result.success,
                    content=result.content,
                    data=result.data,
                )
                tool_traces.append(trace)
                scratchpad_lines.append(
                    f"tool={tool_call.name} success={trace.success} content={trace.content[:300]}"
                )

            if plan.finish_task and not plan.continue_thinking:
                break

        response = self._response_generator.generate(
            user_message=user_message,
            model_outputs=model_outputs,
            tool_traces=tool_traces,
        )
        memory_entries = self._build_memory_entries(
            user_message=user_message,
            response=response,
            tool_traces=tool_traces,
            matched_skills=matched_skills,
        )

        return LoopResult(
            response=response,
            tool_traces=tool_traces,
            model_outputs=model_outputs,
            memory_entries=memory_entries,
            plans=plans,
        )

    def _build_memory_entries(
        self,
        *,
        user_message: str,
        response: str,
        tool_traces: list[ToolCallTrace],
        matched_skills: list[SkillSpec],
    ) -> list[str]:
        entries: list[str] = []

        entries.append(f"user_input: {user_message[:300]}")
        entries.extend(self._extract_user_facts(user_message))

        for skill in matched_skills[:5]:
            entries.append(f"skill_match: id={skill.skill_id} name={skill.name}")

        for trace in tool_traces:
            preview = trace.content.replace("\n", " ")[:260]
            entries.append(
                f"tool_result: tool={trace.call.name} success={trace.success} content={preview}"
            )

        entries.append(f"assistant_output: {response[:400]}")

        deduped: list[str] = []
        for item in entries:
            normalized = item.strip()
            if not normalized:
                continue
            if normalized in deduped:
                continue
            deduped.append(normalized)

        return deduped[:14]

    def _extract_user_facts(self, user_message: str) -> list[str]:
        facts: list[str] = []
        for pattern in _USER_FACT_PATTERNS:
            match = pattern.search(user_message)
            if match:
                facts.append(f"user_fact: name={match.group(1)}")

        if "喜欢" in user_message or "偏好" in user_message:
            facts.append(f"user_fact: preference={user_message[:200]}")

        return facts
