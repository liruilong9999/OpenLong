from __future__ import annotations

from dataclasses import dataclass

from app.agent.loop import AgentLoop
from app.agent.planner import Planner
from app.agent.prompt_builder import PromptBuilder
from app.agent.response_generator import ResponseGenerator
from app.memory.manager import MemoryManager
from app.models.message import ChatMessage
from app.skills.loader import SkillLoader
from app.tools.executor import ToolExecutor
from app.workspace.manager import WorkspaceManager


@dataclass(slots=True)
class AgentProfile:
    agent_id: str


class AgentRuntime:
    def __init__(
        self,
        workspace_manager: WorkspaceManager,
        memory_manager: MemoryManager,
        skill_loader: SkillLoader,
        tool_executor: ToolExecutor,
    ) -> None:
        self._workspace_manager = workspace_manager
        self._memory_manager = memory_manager
        self._skill_loader = skill_loader

        self._planner = Planner()
        self._prompt_builder = PromptBuilder()
        self._loop = AgentLoop(tool_executor=tool_executor, response_generator=ResponseGenerator())

        self._agents: dict[str, AgentProfile] = {}
        self.get_or_create("main")

    def get_or_create(self, agent_id: str) -> AgentProfile:
        profile = self._agents.get(agent_id)
        if profile is None:
            self._workspace_manager.ensure_agent_workspace(agent_id)
            profile = AgentProfile(agent_id=agent_id)
            self._agents[agent_id] = profile
        return profile

    def list_agents(self) -> list[str]:
        return sorted(self._agents.keys())

    async def run_turn(
        self,
        agent_id: str,
        session_id: str,
        user_message: str,
        history: list[ChatMessage],
    ) -> str:
        self.get_or_create(agent_id)

        context_block = self._workspace_manager.load_context_block(agent_id)
        memories = self._memory_manager.retrieve(agent_id=agent_id, query=user_message)
        skills = self._skill_loader.list_skill_names(agent_id)

        # 在此统一构建 Prompt，后续接入不同 LLM 时无需改动外围流程。
        _prompt = self._prompt_builder.build(
            context_block=context_block,
            history=history,
            memories=memories,
            skills=skills,
            user_message=user_message,
        )

        plan = self._planner.plan(user_message)
        result = await self._loop.run(plan=plan, user_message=user_message)

        # 当前轮次的用户输入与系统回复都写入长期记忆。
        self._memory_manager.write(agent_id=agent_id, session_id=session_id, entry=user_message)
        self._memory_manager.write(agent_id=agent_id, session_id=session_id, entry=result.response)

        return result.response
