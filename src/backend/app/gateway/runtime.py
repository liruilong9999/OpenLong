from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.agent.runtime import AgentRuntime
from app.channel.manager import ChannelManager
from app.core.config import Settings
from app.core.events import Event, EventBus
from app.memory.manager import MemoryManager
from app.gateway.agent_manager import AgentManager
from app.gateway.model_router import ModelRouter
from app.gateway.session_manager import SessionManager
from app.gateway.task_queue import TaskKind, TaskQueue
from app.gateway.websocket import WebSocketHub
from app.models.message import ChatMessage, Role
from app.self_evolution.engine import SelfEvolutionEngine
from app.skills.loader import SkillLoader
from app.tools.executor import ToolExecutor
from app.tools.logger import ToolExecutionLogStore
from app.tools.permissions import ToolPermissionManager
from app.tools.registry import ToolRegistry
from app.tools.sandbox import ToolSandbox
from app.tools.builtins.file_tool import FileTool
from app.tools.builtins.http_tool import HttpTool
from app.tools.builtins.shell_tool import ShellTool
from app.tools.builtins.time_tool import TimeTool
from app.tools.builtins.workspace_tool import WorkspaceTool
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
        # 缁熶竴鍒涘缓鍚勫瓙绯荤粺瀹炰緥锛屽舰鎴愮綉鍏宠繍琛屾椂渚濊禆鍥俱€?
        event_bus = EventBus()
        session_manager = SessionManager()
        websocket_hub = WebSocketHub()
        workspace_manager = WorkspaceManager(settings.workspace_root)
        memory_manager = MemoryManager(workspace_manager, event_bus=event_bus)
        skill_loader = SkillLoader(workspace_manager)

        tool_registry = ToolRegistry()
        tool_registry.register(FileTool(workspace_manager))
        tool_registry.register(HttpTool())
        tool_registry.register(ShellTool(enabled=settings.tool_shell_enabled))
        tool_registry.register(TimeTool())
        tool_registry.register(WorkspaceTool(workspace_manager))
        tool_permission_manager = ToolPermissionManager.from_csv(
            allowlist_csv=settings.tool_allowlist,
            denylist_csv=settings.tool_denylist,
            confirmation_csv=settings.tool_confirmation_required,
        )
        tool_log_store = ToolExecutionLogStore(max_records=settings.tool_log_limit)
        tool_executor = ToolExecutor(
            tool_registry,
            event_bus=event_bus,
            permission_manager=tool_permission_manager,
            sandbox=ToolSandbox(),
            log_store=tool_log_store,
        )

        agent_runtime = AgentRuntime.from_settings(
            settings=settings,
            workspace_manager=workspace_manager,
            memory_manager=memory_manager,
            skill_loader=skill_loader,
            tool_executor=tool_executor,
        )

        runtime = cls(
            settings=settings,
            session_manager=session_manager,
            agent_manager=AgentManager(agent_runtime),
            model_router=ModelRouter(settings, event_bus=event_bus),
            task_queue=TaskQueue(event_bus=event_bus),
            websocket_hub=websocket_hub,
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
        runtime._register_event_handlers()
        return runtime

    def _register_event_handlers(self) -> None:
        relay_events = [
            "session.created",
            "session.closed",
            "session.agent_assigned",
            "workspace.created",
            "workspace.deleted",
            "workspace.exported",
            "workspace.imported",
            "context.updated",
            "context.reloaded",
            "skill.reloaded",
            "skill.updated",
            "skill.deleted",
            "user.input.received",
            "agent.execution.started",
            "agent.execution.completed",
            "agent.execution.failed",
            "model.call.completed",
            "tool.execution.completed",
            "tool.execution.denied",
            "memory.write.completed",
            "memory.summary.updated",
            "memory.compressed",
            "memory.decay.applied",
            "task.submitted",
            "task.started",
            "task.completed",
            "task.failed",
        ]

        for event_name in relay_events:
            self.event_bus.subscribe(event_name, self._forward_event_to_websocket)
            self.event_bus.subscribe(event_name, self._write_event_to_workspace_log)

    def _forward_event_to_websocket(self, event: Event) -> None:
        session_id = str(event.payload.get("session_id", "")).strip()
        if not session_id:
            return

        self.websocket_hub.broadcast_nowait(
            session_id=session_id,
            payload={
                "type": "event",
                "name": event.name,
                "timestamp": event.timestamp.isoformat(),
                "payload": event.payload,
            },
        )


    def _resolve_event_agent_id(self, event: Event) -> str | None:
        payload_agent_id = str(event.payload.get("agent_id", "")).strip()
        if payload_agent_id:
            return payload_agent_id

        session_id = str(event.payload.get("session_id", "")).strip()
        if not session_id:
            return None

        session = self.session_manager.get(session_id)
        if session is None:
            return None
        return session.agent_id

    def _write_event_to_workspace_log(self, event: Event) -> None:
        agent_id = self._resolve_event_agent_id(event)
        if not agent_id:
            return

        session_id = str(event.payload.get("session_id", "")).strip()
        self.workspace_manager.append_log(
            agent_id,
            event_name=event.name,
            session_id=session_id,
            message=f"{event.name}: {event.payload}",
            payload=event.payload,
        )

    def list_workspaces(self) -> list[dict[str, Any]]:
        return self.workspace_manager.list_workspaces()

    def workspace_templates(self) -> dict[str, Any]:
        return self.workspace_manager.list_templates()

    def get_workspace(self, agent_id: str) -> dict[str, Any] | None:
        snapshot = self.workspace_manager.load_workspace(agent_id=agent_id, create_if_missing=False)
        if not snapshot.get("exists"):
            return None
        return snapshot

    def create_workspace(
        self,
        agent_id: str,
        template_name: str = "default",
        agent_type: str = "general",
        overwrite: bool = False,
    ) -> dict[str, Any]:
        snapshot = self.workspace_manager.create_workspace(
            agent_id=agent_id,
            template_name=template_name,
            agent_type=agent_type,
            overwrite=overwrite,
        )
        self.agent_runtime.get_or_create(agent_id, agent_type=agent_type)
        self.event_bus.emit(
            "workspace.created",
            {"agent_id": agent_id, "template_name": template_name},
        )
        return snapshot

    def delete_workspace(self, agent_id: str, force: bool = False) -> dict[str, Any]:
        result = self.workspace_manager.delete_workspace(agent_id=agent_id, force=force)
        if result.get("deleted") and agent_id != "main":
            self.agent_manager.stop_agent(agent_id, force=True)
            self.agent_runtime.remove(agent_id)
            self.event_bus.emit("workspace.deleted", {"agent_id": agent_id})
        return result

    def export_workspace(self, agent_id: str, export_dir: str | None = None) -> dict[str, Any]:
        result = self.workspace_manager.export_workspace(agent_id=agent_id, export_dir=export_dir)
        self.event_bus.emit(
            "workspace.exported",
            {"agent_id": agent_id, "archive_path": result["archive_path"]},
        )
        return result

    def import_workspace(self, agent_id: str, archive_path: str, overwrite: bool = False) -> dict[str, Any]:
        result = self.workspace_manager.import_workspace(
            agent_id=agent_id,
            archive_path=archive_path,
            overwrite=overwrite,
        )
        self.agent_runtime.get_or_create(agent_id)
        self.event_bus.emit(
            "workspace.imported",
            {"agent_id": agent_id, "archive_path": archive_path},
        )
        return result

    def workspace_logs(self, agent_id: str, limit: int = 100) -> dict[str, Any]:
        return {
            "agent_id": agent_id,
            "items": self.workspace_manager.recent_logs(agent_id=agent_id, limit=limit),
        }
    def create_session(
        self,
        session_id: str | None = None,
        preferred_agent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        real_session_id = session_id or str(uuid4())
        existing = self.session_manager.get(real_session_id)
        if existing is not None:
            return self.session_manager.get_session_snapshot(real_session_id) or {}

        agent_id = self.agent_manager.assign_session(
            session_id=real_session_id,
            preferred_agent_id=preferred_agent_id,
        )
        self.session_manager.create_session(real_session_id, agent_id=agent_id, metadata=metadata)
        self.event_bus.emit(
            "session.created",
            {"session_id": real_session_id, "agent_id": agent_id},
        )
        return self.session_manager.get_session_snapshot(real_session_id) or {}

    def assign_agent_to_session(self, session_id: str, agent_id: str) -> dict[str, Any] | None:
        session = self.session_manager.get(session_id)
        if session is None:
            self.create_session(session_id=session_id, preferred_agent_id=agent_id)
            session = self.session_manager.get(session_id)

        if session is None:
            return None

        assigned_agent = self.agent_manager.reassign_session(session_id=session_id, new_agent_id=agent_id)
        self.session_manager.assign_agent(session_id=session_id, agent_id=assigned_agent)

        self.event_bus.emit(
            "session.agent_assigned",
            {
                "session_id": session_id,
                "agent_id": assigned_agent,
            },
        )

        return self.session_manager.get_session_snapshot(session_id)

    def close_session(self, session_id: str, reason: str = "manual") -> bool:
        closed = self.session_manager.close_session(session_id=session_id, reason=reason)
        if not closed:
            return False

        self.agent_manager.release_session(session_id)
        self.event_bus.emit("session.closed", {"session_id": session_id, "reason": reason})
        return True

    def get_agent_context(self, agent_id: str, force_refresh: bool = False) -> dict[str, Any]:
        self.agent_manager.ensure_agent(agent_id)
        return self.workspace_manager.get_context_snapshot(agent_id=agent_id, force_refresh=force_refresh)

    def update_agent_context(self, agent_id: str, context_name: str, content: str) -> dict[str, Any]:
        self.agent_manager.ensure_agent(agent_id)
        snapshot = self.workspace_manager.update_context(
            agent_id=agent_id,
            context_name=context_name,
            content=content,
            dynamic_only=True,
        )
        self.event_bus.emit(
            "context.updated",
            {
                "session_id": "",
                "agent_id": agent_id,
                "context_name": context_name,
            },
        )
        return snapshot

    def reload_agent_context(self, agent_id: str) -> dict[str, Any]:
        snapshot = self.get_agent_context(agent_id=agent_id, force_refresh=True)
        self.event_bus.emit(
            "context.reloaded",
            {
                "session_id": "",
                "agent_id": agent_id,
            },
        )
        return snapshot

    def list_agent_skills(self, agent_id: str, force_refresh: bool = False) -> dict[str, Any]:
        self.agent_manager.ensure_agent(agent_id)
        snapshot = self.skill_loader.snapshot(agent_id=agent_id, force_refresh=force_refresh)
        snapshot["cache"] = self.skill_loader.cache_stats()
        return snapshot

    def match_agent_skills(self, agent_id: str, user_message: str, limit: int = 5) -> dict[str, Any]:
        self.agent_manager.ensure_agent(agent_id)
        matches = self.skill_loader.match_with_scores(
            agent_id=agent_id,
            user_message=user_message,
            max_items=limit,
        )
        return {
            "agent_id": agent_id,
            "query": user_message,
            "matches": matches,
        }

    def reload_agent_skills(self, agent_id: str) -> dict[str, Any]:
        self.agent_manager.ensure_agent(agent_id)
        skills = self.skill_loader.reload(agent_id)
        self.event_bus.emit(
            "skill.reloaded",
            {
                "session_id": "",
                "agent_id": agent_id,
                "count": len(skills),
            },
        )
        return self.list_agent_skills(agent_id=agent_id, force_refresh=False)

    def upsert_agent_skill(self, agent_id: str, skill_id: str, markdown: str) -> dict[str, Any]:
        self.agent_manager.ensure_agent(agent_id)
        skill = self.skill_loader.upsert_skill_markdown(agent_id=agent_id, skill_id=skill_id, markdown=markdown)
        self.event_bus.emit(
            "skill.updated",
            {
                "session_id": "",
                "agent_id": agent_id,
                "skill_id": skill.skill_id,
            },
        )
        return skill.to_dict()

    def delete_agent_skill(self, agent_id: str, skill_id: str) -> dict[str, Any]:
        self.agent_manager.ensure_agent(agent_id)
        deleted = self.skill_loader.delete_skill(agent_id=agent_id, skill_id=skill_id)
        if deleted:
            self.event_bus.emit(
                "skill.deleted",
                {
                    "session_id": "",
                    "agent_id": agent_id,
                    "skill_id": skill_id,
                },
            )
        return {"agent_id": agent_id, "skill_id": skill_id, "deleted": deleted}

    def skill_template(self, skill_name: str) -> str:
        return self.skill_loader.render_template(skill_name)

    async def _enqueue_memory_write(
        self,
        *,
        session_id: str,
        agent_id: str,
        entry: str,
        memory_type: str | None = None,
        importance: float | None = None,
        source: str = "api",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        async def _task() -> dict[str, bool]:
            self.memory_manager.write(
                agent_id=agent_id,
                session_id=session_id,
                entry=entry,
                memory_type=memory_type,
                importance=importance,
                source=source,
                metadata=metadata,
            )
            return {"ok": True}

        task_id, _ = await self.task_queue.submit_and_wait(
            kind=TaskKind.MEMORY,
            name="memory.write",
            payload={"session_id": session_id, "agent_id": agent_id},
            task_factory=_task,
        )
        return task_id

    async def handle_user_message(
        self,
        session_id: str,
        user_message: str,
        preferred_agent_id: str | None = None,
        source: str = "api",
    ) -> dict[str, str]:
        if not self.session_manager.get(session_id):
            self.create_session(session_id=session_id, preferred_agent_id=preferred_agent_id)
        elif preferred_agent_id:
            self.assign_agent_to_session(session_id=session_id, agent_id=preferred_agent_id)

        session = self.session_manager.get(session_id)
        if session is None:
            raise RuntimeError(f"failed to initialize session: {session_id}")
        if not self.agent_manager.is_running(session.agent_id):
            self.assign_agent_to_session(session_id=session_id, agent_id="main")
            session = self.session_manager.get(session_id)
            if session is None:
                raise RuntimeError(f"failed to reassign session: {session_id}")

        self.event_bus.emit(
            "user.input.received",
            {
                "session_id": session_id,
                "agent_id": session.agent_id,
                "source": source,
                "message_size": len(user_message),
            },
        )
        self.session_manager.append_message(session_id, ChatMessage(role=Role.USER, content=user_message))

        await self.model_router.dispatch(
            agent_id=session.agent_id,
            task_type="chat",
            prompt_preview=user_message[:200],
            session_id=session_id,
        )

        async def _agent_turn() -> Any:
            self.event_bus.emit(
                "agent.execution.started",
                {"session_id": session_id, "agent_id": session.agent_id},
            )
            try:
                turn_result = await self.agent_runtime.run_turn(
                    agent_id=session.agent_id,
                    session_id=session_id,
                    user_message=user_message,
                    history=session.messages,
                )
            except Exception as exc:
                self.agent_manager.mark_error(session.agent_id, str(exc))
                self.event_bus.emit(
                    "agent.execution.failed",
                    {
                        "session_id": session_id,
                        "agent_id": session.agent_id,
                        "error": str(exc),
                    },
                )
                raise

            self.event_bus.emit(
                "agent.execution.completed",
                {
                    "session_id": session_id,
                    "agent_id": session.agent_id,
                    "reply_size": len(turn_result.reply),
                    "iterations": turn_result.iterations,
                },
            )
            return turn_result

        task_id, turn_result = await self.task_queue.submit_and_wait(
            kind=TaskKind.AGENT,
            name="agent.turn",
            payload={"session_id": session_id, "agent_id": session.agent_id},
            task_factory=_agent_turn,
        )

        self.session_manager.append_message(
            session_id,
            ChatMessage(role=Role.ASSISTANT, content=turn_result.reply),
        )

        return {
            "session_id": session_id,
            "agent_id": session.agent_id,
            "reply": turn_result.reply,
            "task_id": task_id,
        }

    async def execute_tool_task(
        self,
        tool_name: str,
        session_id: str,
        agent_id: str,
        args: dict[str, Any],
        caller: str = "agent",
        confirm: bool = False,
    ) -> dict[str, Any]:
        payload = dict(args)
        payload["session_id"] = session_id
        payload["agent_id"] = agent_id
        payload["caller"] = caller
        payload["confirm"] = confirm

        async def _tool_task() -> Any:
            return await self.tool_executor.execute(tool_name, **payload)

        task_id, result = await self.task_queue.submit_and_wait(
            kind=TaskKind.TOOL,
            name=f"tool.{tool_name}",
            payload={"session_id": session_id, "agent_id": agent_id, "tool_name": tool_name},
            task_factory=_tool_task,
        )

        return {
            "task_id": task_id,
            "tool_name": tool_name,
            "success": result.success,
            "content": result.content,
            "data": result.data,
        }

    def list_tools(self) -> dict[str, Any]:
        snapshot = self.tool_registry.snapshot()
        snapshot["permissions"] = self.tool_executor.permission_snapshot()
        return snapshot

    def tool_logs(self, limit: int = 100, tool_name: str | None = None) -> dict[str, Any]:
        return {
            "stats": self.tool_executor.log_stats(),
            "items": self.tool_executor.recent_logs(limit=limit, tool_name=tool_name),
        }

    async def execute_memory_task(
        self,
        *,
        session_id: str,
        agent_id: str,
        entry: str,
        memory_type: str | None = None,
        importance: float | None = None,
        source: str = "api",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_id = await self._enqueue_memory_write(
            session_id=session_id,
            agent_id=agent_id,
            entry=entry,
            memory_type=memory_type,
            importance=importance,
            source=source,
            metadata=metadata,
        )
        return {"task_id": task_id, "success": True}

    def query_memory(
        self,
        *,
        agent_id: str,
        query: str,
        limit: int = 20,
        memory_type: str | None = None,
        min_weight: float = 0.0,
    ) -> dict[str, Any]:
        return self.memory_manager.query(
            agent_id=agent_id,
            query=query,
            limit=limit,
            memory_type=memory_type,
            min_weight=min_weight,
        )

    def summarize_memory(self, agent_id: str, max_items: int = 120) -> dict[str, Any]:
        return self.memory_manager.summarize(agent_id=agent_id, max_items=max_items)

    def compress_memory(self, agent_id: str) -> dict[str, Any]:
        return self.memory_manager.compress(agent_id=agent_id)

    def decay_memory(self, agent_id: str) -> dict[str, Any]:
        return self.memory_manager.decay(agent_id=agent_id)

    def dashboard_agents(self) -> list[dict[str, Any]]:
        return self.agent_manager.list_agents(include_stopped=True)

    def dashboard_sessions(self) -> list[dict[str, Any]]:
        return self.session_manager.list_sessions(include_closed=True)

    def dashboard_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.event_bus.recent(limit=limit)

    def dashboard_memory(self, agent_id: str) -> dict[str, object]:
        status = self.memory_manager.status(agent_id)
        preview = self.memory_manager.query(agent_id=agent_id, query="", limit=10)
        return {
            **status,
            "recent_items": preview["items"],
        }

    def dashboard_tasks(self, limit: int = 100) -> dict[str, Any]:
        return {
            "stats": self.task_queue.stats(),
            "tasks": self.task_queue.list_tasks(limit=limit),
        }

    def dashboard_models(self, limit: int = 100) -> dict[str, Any]:
        return {
            "stats": self.model_router.stats(),
            "calls": self.model_router.recent_calls(limit=limit),
        }

    def dashboard_tools(self, limit: int = 100, tool_name: str | None = None) -> dict[str, Any]:
        return {
            "registry": self.list_tools(),
            "logs": self.tool_logs(limit=limit, tool_name=tool_name),
        }

    def dashboard_skills(self, agent_id: str, force_refresh: bool = False) -> dict[str, Any]:
        return self.list_agent_skills(agent_id=agent_id, force_refresh=force_refresh)

    def dashboard_workspaces(self) -> dict[str, Any]:
        return {
            "items": self.list_workspaces(),
            "templates": self.workspace_templates(),
        }

    def dashboard_system(self) -> dict[str, Any]:
        return {
            "websocket": self.websocket_hub.snapshot(),
            "task_queue": self.task_queue.stats(),
            "context_cache": self.workspace_manager.context_cache_stats(),
            "skill_cache": self.skill_loader.cache_stats(),
            "tool_logs": self.tool_executor.log_stats(),
            "workspaces": {
                "total": len(self.workspace_manager.list_workspaces()),
                "templates": len(self.workspace_manager.list_templates()["templates"]),
            },
            "sessions": {
                "total": len(self.session_manager.list_sessions(include_closed=True)),
                "active": self.session_manager.active_count(),
            },
        }








