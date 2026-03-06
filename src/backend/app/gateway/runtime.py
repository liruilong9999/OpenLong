from __future__ import annotations

from dataclasses import dataclass

from app.agent.runtime import AgentRuntime
from app.channel.manager import ChannelManager
from app.core.config import Settings
from app.core.events import EventBus
from app.memory.manager import MemoryManager
from app.gateway.agent_manager import AgentManager
from app.gateway.model_router import ModelRouter
from app.gateway.session_manager import SessionManager
from app.gateway.task_queue import TaskQueue
from app.gateway.websocket import WebSocketHub
from app.models.message import ChatMessage, Role
from app.self_evolution.engine import SelfEvolutionEngine
from app.skills.loader import SkillLoader
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.tools.builtins.file_tool import FileTool
from app.tools.builtins.http_tool import HttpTool
from app.tools.builtins.shell_tool import ShellTool
from app.workspace.manager import WorkspaceManager


@dataclass(slots=True)
class GatewayRuntime:
    settings: Settings
    session_manager: SessionManager
    agent_manager: AgentManager
    model_router: ModelRouter
    task_queue: TaskQueue
    websocket_hub: WebSocketHub
    event_bus: EventBus
    workspace_manager: WorkspaceManager
    memory_manager: MemoryManager
    skill_loader: SkillLoader
    tool_registry: ToolRegistry
    tool_executor: ToolExecutor
    channel_manager: ChannelManager
    self_evolution_engine: SelfEvolutionEngine
    agent_runtime: AgentRuntime

    @classmethod
    def from_settings(cls, settings: Settings) -> "GatewayRuntime":
        # 统一创建各子系统实例，形成网关运行时依赖图。
        event_bus = EventBus()
        session_manager = SessionManager()
        workspace_manager = WorkspaceManager(settings.workspace_root)
        memory_manager = MemoryManager(workspace_manager)
        skill_loader = SkillLoader(workspace_manager)

        tool_registry = ToolRegistry()
        tool_registry.register(FileTool(workspace_manager))
        tool_registry.register(HttpTool())
        tool_registry.register(ShellTool(enabled=settings.tool_shell_enabled))
        tool_executor = ToolExecutor(tool_registry)

        agent_runtime = AgentRuntime(
            workspace_manager=workspace_manager,
            memory_manager=memory_manager,
            skill_loader=skill_loader,
            tool_executor=tool_executor,
        )

        return cls(
            settings=settings,
            session_manager=session_manager,
            agent_manager=AgentManager(agent_runtime),
            model_router=ModelRouter(settings),
            task_queue=TaskQueue(),
            websocket_hub=WebSocketHub(),
            event_bus=event_bus,
            workspace_manager=workspace_manager,
            memory_manager=memory_manager,
            skill_loader=skill_loader,
            tool_registry=tool_registry,
            tool_executor=tool_executor,
            channel_manager=ChannelManager(),
            self_evolution_engine=SelfEvolutionEngine(),
            agent_runtime=agent_runtime,
        )

    async def handle_user_message(self, session_id: str, user_message: str) -> dict[str, str]:
        # 1) 记录用户输入。
        session = self.session_manager.get_or_create(session_id=session_id)
        self.session_manager.append_message(session_id, ChatMessage(role=Role.USER, content=user_message))

        # 2) 交给 Agent Runtime 执行单轮推理。
        reply = await self.agent_runtime.run_turn(
            agent_id=session.agent_id,
            session_id=session_id,
            user_message=user_message,
            history=session.messages,
        )

        # 3) 回写助手回复，完成会话闭环。
        self.session_manager.append_message(
            session_id,
            ChatMessage(role=Role.ASSISTANT, content=reply),
        )

        return {
            "session_id": session_id,
            "agent_id": session.agent_id,
            "reply": reply,
        }
