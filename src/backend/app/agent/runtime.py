from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.agent.loop import AgentLoop
from app.agent.model_client import HeuristicModelClient
from app.agent.planner import Planner
from app.agent.prompt_builder import PromptBuilder
from app.agent.response_generator import ResponseGenerator
from app.agent.types import Agent, AgentTask, AgentTaskStatus, AgentTurnResult
from app.memory.manager import MemoryManager
from app.models.message import ChatMessage
from app.skills.loader import SkillLoader
from app.skills.types import SkillSpec
from app.tools.executor import ToolExecutor
from app.workspace.manager import WorkspaceManager


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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

        self._planner = Planner(max_iterations=3)
        self._prompt_builder = PromptBuilder()
        self._loop = AgentLoop(
            tool_executor=tool_executor,
            prompt_builder=self._prompt_builder,
            planner=self._planner,
            model_client=HeuristicModelClient(),
            response_generator=ResponseGenerator(),
            max_iterations=3,
        )

        self._agents: dict[str, Agent] = {}
        self.get_or_create("main")

    def exists(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def get_or_create(self, agent_id: str, agent_type: str = "general") -> Agent:
        agent = self._agents.get(agent_id)
        if agent is None:
            workspace_snapshot = self._workspace_manager.load_workspace(agent_id=agent_id, create_if_missing=True)
            state = self._workspace_manager.load_agent_state(agent_id)
            resolved_type = str(state.get("agent_type") or workspace_snapshot.get("metadata", {}).get("agent_type") or agent_type)
            workspace = Path(workspace_snapshot["path"])
            agent = Agent(agent_id=agent_id, agent_type=resolved_type, workspace=workspace)
            agent.skills = self._skill_loader.list_skill_names(agent_id)
            agent.memory = self._memory_manager.status(agent_id)
            agent.current_task = self._task_from_state(state.get("current_task"))
            self._agents[agent_id] = agent
        return agent

    def remove(self, agent_id: str) -> bool:
        if agent_id == "main":
            return False
        return self._agents.pop(agent_id, None) is not None

    def list_agents(self) -> list[str]:
        return sorted(self._agents.keys())

    def get_agent_snapshot(self, agent_id: str) -> dict[str, object] | None:
        agent = self._agents.get(agent_id)
        if agent is None:
            return None

        return {
            "agent_id": agent.agent_id,
            "agent_type": agent.agent_type,
            "workspace": str(agent.workspace),
            "skills": agent.skills,
            "memory": agent.memory,
            "current_task": self._serialize_task(agent.current_task),
        }

    def _resolve_skills(self, agent_id: str, user_message: str) -> tuple[list[SkillSpec], list[SkillSpec]]:
        skills = self._skill_loader.load(agent_id)
        matched_skills = self._skill_loader.match(agent_id, user_message=user_message, max_items=5)
        return skills, matched_skills

    async def run_turn(
        self,
        agent_id: str,
        session_id: str,
        user_message: str,
        history: list[ChatMessage],
    ) -> AgentTurnResult:
        agent = self.get_or_create(agent_id)
        skills, matched_skills = self._resolve_skills(agent_id, user_message)

        agent.skills = [item.name for item in skills]
        agent.memory = self._memory_manager.status(agent_id)

        task = AgentTask(task_id=str(uuid4()), input_text=user_message, status=AgentTaskStatus.RUNNING)
        agent.current_task = task
        self._persist_agent_state(agent)

        try:
            context_block = self._workspace_manager.load_context_block(agent_id)
            memories = self._memory_manager.retrieve(agent_id=agent_id, query=user_message)

            loop_result = await self._loop.run(
                agent=agent,
                session_id=session_id,
                user_message=user_message,
                history=history,
                context_block=context_block,
                memories=memories,
                skills=skills,
                matched_skills=matched_skills,
                task_id=task.task_id,
            )

            for entry in loop_result.memory_entries:
                self._memory_manager.write(agent_id=agent_id, session_id=session_id, entry=entry)

            task.status = AgentTaskStatus.COMPLETED
            task.finished_at = _utc_now()
            agent.memory = self._memory_manager.status(agent_id)
            self._persist_agent_state(agent)

            return AgentTurnResult(
                reply=loop_result.response,
                tool_outputs=[
                    f"{trace.call.name}: {trace.content}" for trace in loop_result.tool_traces
                ],
                memory_entries=loop_result.memory_entries,
                model_outputs=[output.text for output in loop_result.model_outputs],
                iterations=max(len(loop_result.plans), 1),
            )
        except Exception as exc:
            task.status = AgentTaskStatus.FAILED
            task.error = str(exc)
            task.finished_at = _utc_now()
            self._persist_agent_state(agent)
            raise

    def _persist_agent_state(self, agent: Agent) -> None:
        self._workspace_manager.save_agent_state(
            agent.agent_id,
            {
                "agent_type": agent.agent_type,
                "current_task": self._serialize_task(agent.current_task),
                "skills": list(agent.skills),
                "memory_summary": {
                    "entries": agent.memory.get("entries", 0),
                    "by_type": agent.memory.get("by_type", {}),
                },
            },
        )

    def _serialize_task(self, task: AgentTask | None) -> dict[str, object] | None:
        if task is None:
            return None
        return {
            "task_id": task.task_id,
            "input_text": task.input_text,
            "status": task.status.value,
            "started_at": task.started_at.isoformat(),
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
            "error": task.error,
        }

    def _task_from_state(self, payload: object) -> AgentTask | None:
        if not isinstance(payload, dict):
            return None
        task_id = str(payload.get("task_id", "")).strip()
        input_text = str(payload.get("input_text", "")).strip()
        if not task_id or not input_text:
            return None
        status_text = str(payload.get("status", AgentTaskStatus.RUNNING.value))
        try:
            status = AgentTaskStatus(status_text)
        except ValueError:
            status = AgentTaskStatus.RUNNING
        task = AgentTask(task_id=task_id, input_text=input_text, status=status)
        started_at = payload.get("started_at")
        finished_at = payload.get("finished_at")
        if isinstance(started_at, str) and started_at:
            task.started_at = datetime.fromisoformat(started_at)
        if isinstance(finished_at, str) and finished_at:
            task.finished_at = datetime.fromisoformat(finished_at)
        error = payload.get("error")
        task.error = str(error) if error else None
        return task
