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
        websocket_hub = WebSocketHub()
        workspace_manager = WorkspaceManager(settings.workspace_root)
        session_manager = SessionManager(storage_dir=workspace_manager.workspace_root / "_sessions")
        memory_manager = MemoryManager(workspace_manager, event_bus=event_bus)
        skill_loader = SkillLoader(workspace_manager)

        tool_registry = ToolRegistry()
        tool_registry.register(FileTool(workspace_manager))
        tool_registry.register(HttpTool())
        tool_registry.register(
            ShellTool(
                enabled=settings.tool_shell_enabled,
                project_root=workspace_manager.project_root,
                workspace_root=workspace_manager.workspace_root,
            )
        )
        tool_registry.register(TimeTool())
        tool_registry.register(WorkspaceTool(workspace_manager))
        tool_permission_manager = ToolPermissionManager.from_settings(
            profile=settings.tool_profile,
            available_tools=tool_registry.list_tools(),
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
        model_router = ModelRouter(settings, event_bus=event_bus)

        agent_runtime = AgentRuntime.from_settings(
            settings=settings,
            workspace_manager=workspace_manager,
            memory_manager=memory_manager,
            skill_loader=skill_loader,
            tool_executor=tool_executor,
            model_router=model_router,
        )

        runtime = cls(
            settings=settings,
            session_manager=session_manager,
            agent_manager=AgentManager(agent_runtime),
            model_router=model_router,
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
        runtime._restore_session_runtime_state()
        runtime._sync_workspace_runtime_docs("main")
        return runtime

    def _restore_session_runtime_state(self) -> None:
        for session in self.session_manager.list_sessions(include_closed=True):
            agent_id = str(session.get("agent_id") or "main")
            self.agent_manager.create_agent(agent_id)
            if session.get("status") != "active":
                continue
            self.agent_manager.assign_session(
                session_id=str(session["session_id"]),
                preferred_agent_id=agent_id,
            )

    def _register_event_handlers(self) -> None:
        relay_events = [
            "session.created",
            "session.closed",
            "session.agent_assigned",
            "workspace.created",
            "workspace.deleted",
            "workspace.exported",
            "workspace.imported",
            "workspace.file_uploaded",
            "workspace.file_updated",
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
            "tool.execution.stream",
            "tool.approval.created",
            "tool.approval.approved",
            "tool.approval.rejected",
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

    def list_file_tree(
        self,
        *,
        agent_id: str,
        scope: str = "project",
        root_path: str = "",
        max_depth: int = 4,
    ) -> dict[str, Any]:
        return self.workspace_manager.list_file_tree(
            agent_id=agent_id,
            scope=scope,
            root_path=root_path,
            max_depth=max_depth,
        )

    def read_file(self, *, agent_id: str, path: str, scope: str = "auto") -> dict[str, Any]:
        return self.workspace_manager.read_file(agent_id=agent_id, path=path, scope=scope)

    def write_file(self, *, agent_id: str, path: str, content: str, scope: str = "auto") -> dict[str, Any]:
        result = self.workspace_manager.write_file(agent_id=agent_id, path=path, content=content, scope=scope)
        self.event_bus.emit(
            "workspace.file_updated",
            {
                "session_id": "",
                "agent_id": agent_id,
                "path": result["relative_path"],
                "scope": result["scope"],
            },
        )
        return result

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
        self._sync_workspace_runtime_docs(agent_id)
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
        self._sync_workspace_runtime_docs(agent_id)
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

    def list_session_uploads(self, session_id: str, agent_id: str | None = None) -> dict[str, Any]:
        session = self.session_manager.get(session_id)
        resolved_agent_id = agent_id or (session.agent_id if session is not None else "main")
        self.agent_manager.ensure_agent(resolved_agent_id)
        items = [
            self._decorate_upload_item(session_id=session_id, item=item)
            for item in self.workspace_manager.list_session_uploads(
                resolved_agent_id,
                session_id=session_id,
            )
        ]
        return {
            "session_id": session_id,
            "agent_id": resolved_agent_id,
            "items": items,
        }

    def store_session_upload(
        self,
        *,
        session_id: str,
        filename: str,
        content: bytes,
        content_type: str = "application/octet-stream",
        preferred_agent_id: str | None = None,
    ) -> dict[str, Any]:
        session_snapshot = self.create_session(
            session_id=session_id,
            preferred_agent_id=preferred_agent_id,
        )
        agent_id = str(session_snapshot.get("agent_id") or preferred_agent_id or "main")
        item = self.workspace_manager.store_session_upload(
            agent_id,
            session_id=session_id,
            filename=filename,
            content=content,
            content_type=content_type,
        )
        item = self._decorate_upload_item(session_id=session_id, item=item)
        self.event_bus.emit(
            "workspace.file_uploaded",
            {
                "session_id": session_id,
                "agent_id": agent_id,
                "filename": item["filename"],
                "relative_path": item["relative_path"],
                "size": item["size"],
            },
        )
        return item

    def get_session_upload(self, session_id: str, saved_name: str, agent_id: str | None = None) -> dict[str, Any] | None:
        session = self.session_manager.get(session_id)
        resolved_agent_id = agent_id or (session.agent_id if session is not None else "main")
        self.agent_manager.ensure_agent(resolved_agent_id)
        path = self.workspace_manager.get_session_upload_path(
            resolved_agent_id,
            session_id=session_id,
            saved_name=saved_name,
        )
        if path is None:
            return None

        for item in self.workspace_manager.list_session_uploads(resolved_agent_id, session_id=session_id):
            if item.get("saved_name") == path.name:
                return self._decorate_upload_item(session_id=session_id, item=item)

        return self._decorate_upload_item(
            session_id=session_id,
            item={
                "agent_id": resolved_agent_id,
                "session_id": session_id,
                "saved_name": path.name,
                "filename": path.name,
                "relative_path": path.relative_to(self.workspace_manager.workspace_root / resolved_agent_id).as_posix(),
                "absolute_path": str(path),
                "content_type": "application/octet-stream",
                "size": path.stat().st_size,
            },
        )

    def _decorate_upload_item(self, *, session_id: str, item: dict[str, Any]) -> dict[str, Any]:
        payload = dict(item)
        saved_name = str(payload.get("saved_name") or payload.get("filename") or "")
        if saved_name:
            payload["preview_url"] = f"/sessions/{session_id}/attachments/{saved_name}"
        return payload

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
        attachments: list[dict[str, Any]] | None = None,
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
                "attachments": len(attachments or []),
            },
        )
        self.session_manager.append_message(
            session_id,
            ChatMessage(
                role=Role.USER,
                content=self._history_user_content(user_message, attachments or []),
                attachments=list(attachments or []),
            ),
        )

        task_type = self._resolve_task_type(user_message)

        async def _agent_turn() -> Any:
            self.event_bus.emit(
                "agent.execution.started",
                {"session_id": session_id, "agent_id": session.agent_id, "task_type": task_type},
            )
            try:
                turn_result = await self.agent_runtime.run_turn(
                    agent_id=session.agent_id,
                    session_id=session_id,
                    task_type=task_type,
                    user_message=user_message,
                    attachments=attachments,
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
                        "task_type": task_type,
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
                    "task_type": task_type,
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
        self._complete_bootstrap_if_needed(
            agent_id=session.agent_id,
            user_message=user_message,
            assistant_reply=turn_result.reply,
        )
        self._sync_workspace_runtime_docs(session.agent_id)

        return {
            "session_id": session_id,
            "agent_id": session.agent_id,
            "reply": turn_result.reply,
            "task_id": task_id,
        }

    def _history_user_content(self, user_message: str, attachments: list[dict[str, Any]]) -> str:
        base = user_message.strip()
        if not attachments:
            return base

        attachment_names = ", ".join(
            str(item.get("filename") or item.get("saved_name") or item.get("relative_path") or "attachment")
            for item in attachments[:6]
        )
        if base:
            return f"{base}\n[attachments] {attachment_names}"
        return f"[attachments] {attachment_names}"

    def _complete_bootstrap_if_needed(
        self,
        *,
        agent_id: str,
        user_message: str,
        assistant_reply: str,
    ) -> None:
        if not self.workspace_manager.has_workspace_file(agent_id, "BOOTSTRAP.md"):
            return

        snapshot = self.workspace_manager.get_context_snapshot(agent_id)
        user_body = str(snapshot["files"].get("USER.md", {}).get("body", "")).strip()
        style_body = str(snapshot["files"].get("STYLE.md", {}).get("body", "")).strip()

        if not user_body or user_body == "Describe user profile and preferences.":
            self.workspace_manager.write_workspace_file(
                agent_id,
                "USER.md",
                self._render_bootstrap_user_profile(user_message),
            )

        if not style_body or style_body == "Define response style and format.":
            self.workspace_manager.write_workspace_file(
                agent_id,
                "STYLE.md",
                self._render_bootstrap_style(user_message),
            )

        self.workspace_manager.complete_bootstrap(
            agent_id,
            user_message=user_message,
            assistant_reply=assistant_reply,
        )

    def _render_bootstrap_user_profile(self, user_message: str) -> str:
        lines = [
            "# USER",
            "## First Intent",
            f"- 首次需求：{user_message[:300]}",
        ]
        if any(token in user_message for token in ["Python", "python"]):
            lines.append("- 兴趣偏好：提到 Python 相关任务")
        if any(token in user_message for token in ["简洁", "简短", "直接"]):
            lines.append("- 回复偏好：偏好简洁直接")
        if any(token in user_message for token in ["中文", "汉语"]):
            lines.append("- 语言偏好：中文")
        return "\n".join(lines)

    def _render_bootstrap_style(self, user_message: str) -> str:
        rules = [
            "# STYLE",
            "- 默认使用简体中文回答。",
            "- 优先给出结论，再补充关键细节。",
            "- 保持简洁，必要时再展开。",
        ]
        if any(token in user_message for token in ["详细", "展开"]):
            rules.append("- 当前用户允许在需要时展开说明。")
        return "\n".join(rules)

    def _sync_workspace_runtime_docs(self, agent_id: str) -> None:
        self.workspace_manager.write_workspace_file(agent_id, "AGENTS.md", self._render_agents_guide(agent_id))
        self.workspace_manager.write_workspace_file(agent_id, "TOOLS.md", self._render_tools_guide(agent_id))
        self.workspace_manager.write_workspace_file(agent_id, "HEARTBEAT.md", self._render_heartbeat(agent_id))

    def _render_agents_guide(self, agent_id: str) -> str:
        endpoint = self.model_router.endpoint_for(agent_id, task_type="chat")
        workspace = self.workspace_manager.load_workspace(agent_id)
        metadata = workspace.get("metadata", {})
        return "\n".join(
            [
                "# AGENTS",
                f"- agent_id: {agent_id}",
                f"- agent_type: {metadata.get('agent_type', 'general')}",
                f"- template: {metadata.get('template_name', 'default')}",
                f"- model: {endpoint.provider}/{endpoint.model}",
                "- 优先在工作区内完成任务，再调用外部能力。",
                "- 工具调用后要总结结果，不要只回传原始输出。",
                "- 除非用户明确要求，默认使用简体中文并保持简洁。",
            ]
        )

    def _render_tools_guide(self, agent_id: str) -> str:
        del agent_id
        permission = self.tool_executor.permission_snapshot()
        allowed = set(permission["allowlist"])
        confirmation_required = set(permission["confirmation_required"])

        lines = [
            "# TOOLS",
            f"- profile: {permission['profile']}",
            f"- shell_enabled: {str(self.settings.tool_shell_enabled).lower()}",
            f"- confirmation_required: {', '.join(sorted(confirmation_required)) if confirmation_required else 'none'}",
            "",
            "## Enabled Tools",
        ]

        blocked: list[str] = []
        for spec in self.tool_registry.list_specs():
            if spec.name not in allowed:
                blocked.append(spec.name)
                continue

            param_names = ", ".join(param.name for param in spec.parameters) or "none"
            suffix = " (requires confirmation)" if spec.name in confirmation_required else ""
            if spec.name == "shell" and not self.settings.tool_shell_enabled:
                suffix = f"{suffix} (runtime disabled)"
            lines.append(f"- {spec.name}: {spec.description} | params: {param_names}{suffix}")

        if blocked:
            lines.extend(["", "## Blocked Tools"])
            for name in blocked:
                lines.append(f"- {name}")

        return "\n".join(lines)

    def _render_heartbeat(self, agent_id: str) -> str:
        endpoint = self.model_router.endpoint_for(agent_id, task_type="chat")
        memory = self.memory_manager.status(agent_id)
        workspace = self.workspace_manager.load_workspace(agent_id)
        sessions = [item for item in self.session_manager.list_sessions(include_closed=True) if item["agent_id"] == agent_id]
        active_sessions = sum(1 for item in sessions if item["status"] == "active")
        bootstrap_status = "pending" if workspace.get("bootstrap_pending") else "completed"
        permission = self.tool_executor.permission_snapshot()

        return "\n".join(
            [
                "# HEARTBEAT",
                f"- updated_at: {self.event_bus.recent(limit=1)[0]['timestamp'] if self.event_bus.recent(limit=1) else ''}",
                f"- agent_id: {agent_id}",
                f"- workspace: {workspace.get('path', '')}",
                f"- bootstrap: {bootstrap_status}",
                f"- model: {endpoint.provider}/{endpoint.model}",
                f"- tool_profile: {permission['profile']}",
                f"- sessions_total: {len(sessions)}",
                f"- sessions_active: {active_sessions}",
                f"- memory_entries: {memory.get('entries', 0)}",
                f"- memory_types: {memory.get('by_type', {})}",
            ]
        )

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

    def tool_approvals(self, limit: int = 20) -> dict[str, Any]:
        return self.tool_executor.approval_snapshot(limit=limit)

    async def approve_tool_approval(self, approval_id: str) -> dict[str, Any] | None:
        return await self.tool_executor.approve(approval_id)

    def reject_tool_approval(self, approval_id: str, reason: str = "manual reject") -> dict[str, Any] | None:
        return self.tool_executor.reject(approval_id, reason=reason)

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
            "routes": self.model_router.route_snapshot(),
            "calls": self.model_router.recent_calls(limit=limit),
        }

    def _resolve_task_type(self, user_message: str) -> str:
        normalized = (user_message or "").lower()
        if any(token in normalized for token in ["总结", "摘要", "总结一下", "summary", "summarize"]):
            return "summary"
        if any(token in normalized for token in ["记忆", "memory", "回忆", "recall"]):
            return "memory"
        if any(token in normalized for token in ["代码", "bug", "fix", "debug", "工程", "project", "repo", "前端", "后端"]):
            return "coding"
        return "chat"

    def dashboard_tools(self, limit: int = 100, tool_name: str | None = None) -> dict[str, Any]:
        return {
            "registry": self.list_tools(),
            "logs": self.tool_logs(limit=limit, tool_name=tool_name),
            "approvals": self.tool_approvals(limit=20),
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
            "tool_approvals": self.tool_executor.approval_snapshot(limit=10),
            "shell_logs": self.tool_logs(limit=10, tool_name="shell"),
            "workspaces": {
                "total": len(self.workspace_manager.list_workspaces()),
                "templates": len(self.workspace_manager.list_templates()["templates"]),
            },
            "sessions": {
                "total": len(self.session_manager.list_sessions(include_closed=True)),
                "active": self.session_manager.active_count(),
            },
        }








