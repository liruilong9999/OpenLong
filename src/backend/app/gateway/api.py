from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core.security import authenticate_credentials, gateway_auth_enabled


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None
    agent_id: str | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class ChatResponse(BaseModel):
    session_id: str
    agent_id: str
    reply: str
    task_id: str


class SessionCreateRequest(BaseModel):
    session_id: str | None = None
    agent_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionAssignRequest(BaseModel):
    agent_id: str = Field(min_length=1)


class SessionCloseRequest(BaseModel):
    reason: str = Field(default="manual")


class WorkspaceCreateRequest(BaseModel):
    template_name: str = Field(default="default")
    agent_type: str = Field(default="general")
    overwrite: bool = False


class WorkspaceBackupRequest(BaseModel):
    export_dir: str | None = None


class WorkspaceRestoreRequest(BaseModel):
    archive_path: str
    overwrite: bool = False


class AgentCreateRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    template_name: str = Field(default="default")
    agent_type: str = Field(default="general")


class AgentStopRequest(BaseModel):
    force: bool = False


class ToolTaskRequest(BaseModel):
    tool_name: str = Field(min_length=1)
    session_id: str
    agent_id: str = Field(default="main")
    args: dict[str, Any] = Field(default_factory=dict)
    caller: str = Field(default="agent")
    confirm: bool = False


class ToolApprovalDecisionRequest(BaseModel):
    reason: str = Field(default="manual reject")


class MemoryTaskRequest(BaseModel):
    session_id: str
    agent_id: str = Field(default="main")
    entry: str = Field(min_length=1)
    memory_type: str | None = None
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    source: str = Field(default="api")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextUpdateRequest(BaseModel):
    content: str = Field(default="")


class SkillUpsertRequest(BaseModel):
    markdown: str = Field(default="")


class PluginUpsertRequest(BaseModel):
    manifest: dict[str, Any] = Field(default_factory=dict)
    skills: dict[str, str] = Field(default_factory=dict)


class PluginStateRequest(BaseModel):
    enabled: bool = True


class FileContentUpsertRequest(BaseModel):
    path: str = Field(min_length=1)
    content: str = Field(default="")
    agent_id: str = Field(default="main")
    scope: str = Field(default="auto")


class AutomationUpsertRequest(BaseModel):
    name: str = Field(min_length=1)
    agent_id: str = Field(default="main")
    prompt: str = Field(min_length=1)
    cron: str = Field(min_length=1)
    enabled: bool = True
    session_target: str = Field(default="isolated")
    delivery_mode: str = Field(default="none")
    delivery_to: str = Field(default="")
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_api_router() -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        return request.app.state.runtime.health(agent_id="main", task_type="chat")

    @router.get("/ready")
    async def ready(request: Request, response: Response) -> dict[str, Any]:
        payload = request.app.state.runtime.readiness()
        response.status_code = status.HTTP_200_OK if payload["status"] == "ready" else status.HTTP_503_SERVICE_UNAVAILABLE
        return payload

    @router.get("/logs")
    async def logs(request: Request, limit: int = 100, event_name: str | None = None) -> dict[str, Any]:
        return request.app.state.runtime.logs(limit=limit, event_name=event_name)

    @router.get("/doctor")
    async def doctor(request: Request, response: Response) -> dict[str, Any]:
        payload = request.app.state.runtime.doctor()
        response.status_code = status.HTTP_200_OK if payload["status"] == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE
        return payload

    @router.get("/self-evolution")
    async def self_evolution(request: Request, agent_id: str = "main") -> dict[str, Any]:
        return request.app.state.runtime.self_evolution_report(agent_id=agent_id)

    @router.post("/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest, request: Request) -> ChatResponse:
        runtime = request.app.state.runtime
        session_id = body.session_id or str(uuid4())
        result = await runtime.handle_user_message(
            session_id=session_id,
            user_message=body.message,
            preferred_agent_id=body.agent_id,
            source="api",
            attachments=body.attachments,
        )
        return ChatResponse(**result)

    @router.websocket("/ws/{session_id}")
    async def ws_chat(websocket: WebSocket, session_id: str) -> None:
        settings = websocket.app.state.settings
        if gateway_auth_enabled(settings):
            ok, reason = authenticate_credentials(
                settings=settings,
                headers=websocket.headers,
                query_params=websocket.query_params,
            )
            if not ok:
                await websocket.close(code=1008, reason=reason or "unauthorized")
                return

        runtime = websocket.app.state.runtime
        runtime.create_session(session_id=session_id)
        await runtime.websocket_hub.connect(session_id=session_id, websocket=websocket)
        await websocket.send_json({"type": "ws.connected", "session_id": session_id})

        try:
            while True:
                payload = await websocket.receive_json()
                message = str(payload.get("message", "")).strip()
                if not message:
                    await websocket.send_json({"type": "error", "error": "message is required"})
                    continue

                agent_id = payload.get("agent_id")
                result = await runtime.handle_user_message(
                    session_id=session_id,
                    user_message=message,
                    preferred_agent_id=agent_id,
                    source="websocket",
                )
                await websocket.send_json({"type": "chat.reply", **result})
        except WebSocketDisconnect:
            runtime.websocket_hub.disconnect(session_id=session_id, websocket=websocket)

    @router.get("/sessions")
    async def list_sessions(request: Request) -> list[dict[str, Any]]:
        return request.app.state.runtime.session_manager.list_sessions(include_closed=True)

    @router.post("/sessions")
    async def create_session(body: SessionCreateRequest, request: Request) -> dict[str, Any]:
        return request.app.state.runtime.create_session(
            session_id=body.session_id,
            preferred_agent_id=body.agent_id,
            metadata=body.metadata,
        )

    @router.get("/sessions/{session_id}")
    async def get_session(session_id: str, request: Request) -> dict[str, Any]:
        snapshot = request.app.state.runtime.session_manager.get_session_snapshot(session_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="session not found")
        return snapshot

    @router.get("/sessions/{session_id}/history")
    async def get_session_history(session_id: str, request: Request, limit: int = 100) -> list[dict[str, Any]]:
        return request.app.state.runtime.session_manager.get_history(session_id=session_id, limit=limit)

    @router.get("/sessions/{session_id}/attachments")
    async def list_session_attachments(
        session_id: str,
        request: Request,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        return request.app.state.runtime.list_session_uploads(session_id=session_id, agent_id=agent_id)

    @router.post("/sessions/{session_id}/attachments")
    async def upload_session_attachments(
        session_id: str,
        request: Request,
        files: list[UploadFile] = File(...),
        agent_id: str | None = Form(default=None),
    ) -> dict[str, Any]:
        if not files:
            raise HTTPException(status_code=400, detail="no files uploaded")

        items: list[dict[str, Any]] = []
        for upload in files:
            content = await upload.read()
            if not content:
                continue
            items.append(
                request.app.state.runtime.store_session_upload(
                    session_id=session_id,
                    filename=upload.filename or "upload.bin",
                    content=content,
                    content_type=upload.content_type or "application/octet-stream",
                    preferred_agent_id=agent_id,
                )
            )

        if not items:
            raise HTTPException(status_code=400, detail="all uploaded files were empty")

        return {
            "session_id": session_id,
            "agent_id": items[0]["agent_id"],
            "items": items,
        }

    @router.get("/sessions/{session_id}/attachments/{saved_name}")
    async def get_session_attachment(
        session_id: str,
        saved_name: str,
        request: Request,
        agent_id: str | None = None,
    ) -> FileResponse:
        item = request.app.state.runtime.get_session_upload(
            session_id=session_id,
            saved_name=saved_name,
            agent_id=agent_id,
        )
        if item is None:
            raise HTTPException(status_code=404, detail="attachment not found")

        return FileResponse(
            path=item["absolute_path"],
            media_type=item.get("content_type") or "application/octet-stream",
            filename=item.get("filename") or item.get("saved_name") or saved_name,
        )

    @router.get("/files/tree")
    async def file_tree(
        request: Request,
        agent_id: str = "main",
        scope: str = "project",
        root_path: str = "",
        max_depth: int = 4,
    ) -> dict[str, Any]:
        try:
            return request.app.state.runtime.list_file_tree(
                agent_id=agent_id,
                scope=scope,
                root_path=root_path,
                max_depth=max_depth,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/files/content")
    async def file_content(
        request: Request,
        path: str,
        agent_id: str = "main",
        scope: str = "auto",
    ) -> dict[str, Any]:
        try:
            return request.app.state.runtime.read_file(agent_id=agent_id, path=path, scope=scope)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.put("/files/content")
    async def save_file_content(body: FileContentUpsertRequest, request: Request) -> dict[str, Any]:
        try:
            return request.app.state.runtime.write_file(
                agent_id=body.agent_id,
                path=body.path,
                content=body.content,
                scope=body.scope,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/sessions/{session_id}/assign-agent")
    async def assign_agent(session_id: str, body: SessionAssignRequest, request: Request) -> dict[str, Any]:
        snapshot = request.app.state.runtime.assign_agent_to_session(session_id=session_id, agent_id=body.agent_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="session not found")
        return snapshot

    @router.post("/sessions/{session_id}/close")
    async def close_session(session_id: str, body: SessionCloseRequest, request: Request) -> dict[str, bool]:
        closed = request.app.state.runtime.close_session(session_id=session_id, reason=body.reason)
        if not closed:
            raise HTTPException(status_code=404, detail="session not found")
        return {"closed": True}

    @router.get("/automations")
    async def list_automations(request: Request) -> dict[str, Any]:
        return request.app.state.runtime.list_automations()

    @router.post("/automations")
    async def create_automation(body: AutomationUpsertRequest, request: Request) -> dict[str, Any]:
        return request.app.state.runtime.create_automation(
            name=body.name,
            agent_id=body.agent_id,
            prompt=body.prompt,
            cron=body.cron,
            enabled=body.enabled,
            session_target=body.session_target,
            delivery_mode=body.delivery_mode,
            delivery_to=body.delivery_to,
            metadata=body.metadata,
        )

    @router.post("/automations/run-due")
    async def run_due_automations(request: Request) -> list[dict[str, Any]]:
        return await request.app.state.runtime.run_due_automations()

    @router.get("/automations/runs")
    async def automation_runs(request: Request, job_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        return request.app.state.runtime.automation_runs(job_id=job_id, limit=limit)

    @router.get("/automations/{job_id}")
    async def get_automation(job_id: str, request: Request) -> dict[str, Any]:
        payload = request.app.state.runtime.get_automation(job_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="automation not found")
        return payload

    @router.put("/automations/{job_id}")
    async def update_automation(job_id: str, body: AutomationUpsertRequest, request: Request) -> dict[str, Any]:
        try:
            return request.app.state.runtime.update_automation(
                job_id,
                name=body.name,
                agent_id=body.agent_id,
                prompt=body.prompt,
                cron=body.cron,
                enabled=body.enabled,
                session_target=body.session_target,
                delivery_mode=body.delivery_mode,
                delivery_to=body.delivery_to,
                metadata=body.metadata,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.delete("/automations/{job_id}")
    async def delete_automation(job_id: str, request: Request) -> dict[str, Any]:
        payload = request.app.state.runtime.delete_automation(job_id)
        if not payload.get("deleted"):
            raise HTTPException(status_code=404, detail="automation not found")
        return payload

    @router.post("/automations/{job_id}/run")
    async def run_automation(job_id: str, request: Request) -> dict[str, Any]:
        try:
            return await request.app.state.runtime.run_automation(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/workspaces/templates")
    async def workspace_templates(request: Request) -> dict[str, Any]:
        return request.app.state.runtime.workspace_templates()

    @router.get("/workspaces")
    async def list_workspaces(request: Request) -> list[dict[str, Any]]:
        return request.app.state.runtime.list_workspaces()

    @router.post("/workspaces/{agent_id}")
    async def create_workspace(agent_id: str, body: WorkspaceCreateRequest, request: Request) -> dict[str, Any]:
        try:
            return request.app.state.runtime.create_workspace(
                agent_id=agent_id,
                template_name=body.template_name,
                agent_type=body.agent_type,
                overwrite=body.overwrite,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/workspaces/{agent_id}")
    async def get_workspace(agent_id: str, request: Request) -> dict[str, Any]:
        snapshot = request.app.state.runtime.get_workspace(agent_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="workspace not found")
        return snapshot

    @router.delete("/workspaces/{agent_id}")
    async def delete_workspace(agent_id: str, request: Request, force: bool = False) -> dict[str, Any]:
        result = request.app.state.runtime.delete_workspace(agent_id=agent_id, force=force)
        if not result.get("deleted"):
            raise HTTPException(status_code=400, detail=result.get("reason", "workspace delete failed"))
        return result

    @router.get("/workspaces/{agent_id}/logs")
    async def workspace_logs(agent_id: str, request: Request, limit: int = 100) -> dict[str, Any]:
        return request.app.state.runtime.workspace_logs(agent_id=agent_id, limit=limit)

    @router.post("/workspaces/{agent_id}/backup")
    async def backup_workspace(agent_id: str, body: WorkspaceBackupRequest, request: Request) -> dict[str, Any]:
        return request.app.state.runtime.export_workspace(agent_id=agent_id, export_dir=body.export_dir)

    @router.post("/workspaces/{agent_id}/restore")
    async def restore_workspace(agent_id: str, body: WorkspaceRestoreRequest, request: Request) -> dict[str, Any]:
        try:
            return request.app.state.runtime.import_workspace(
                agent_id=agent_id,
                archive_path=body.archive_path,
                overwrite=body.overwrite,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/agents")
    async def list_agents(request: Request) -> list[dict[str, Any]]:
        return request.app.state.runtime.agent_manager.list_agents(include_stopped=True)

    @router.post("/agents")
    async def create_agent(body: AgentCreateRequest, request: Request) -> dict[str, Any]:
        return request.app.state.runtime.create_agent(
            agent_id=body.agent_id,
            template_name=body.template_name,
            agent_type=body.agent_type,
        )

    @router.delete("/agents/{agent_id}")
    async def delete_agent(agent_id: str, request: Request) -> dict[str, Any]:
        result = request.app.state.runtime.delete_agent(agent_id=agent_id)
        if not result.get("deleted"):
            raise HTTPException(status_code=400, detail=result.get("reason", "agent delete failed"))
        return result

    @router.get("/agents/{agent_id}/context")
    async def get_agent_context(agent_id: str, request: Request, force_refresh: bool = False) -> dict[str, Any]:
        try:
            return request.app.state.runtime.get_agent_context(agent_id=agent_id, force_refresh=force_refresh)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/agents/{agent_id}/context/reload")
    async def reload_agent_context(agent_id: str, request: Request) -> dict[str, Any]:
        try:
            return request.app.state.runtime.reload_agent_context(agent_id=agent_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/agents/{agent_id}/context/{context_name}")
    async def update_agent_context(
        agent_id: str,
        context_name: str,
        body: ContextUpdateRequest,
        request: Request,
    ) -> dict[str, Any]:
        try:
            return request.app.state.runtime.update_agent_context(
                agent_id=agent_id,
                context_name=context_name,
                content=body.content,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/agents/{agent_id}/skills")
    async def list_agent_skills(agent_id: str, request: Request, force_refresh: bool = False) -> dict[str, Any]:
        return request.app.state.runtime.list_agent_skills(agent_id=agent_id, force_refresh=force_refresh)

    @router.get("/agents/{agent_id}/skills/match")
    async def match_agent_skills(
        agent_id: str,
        request: Request,
        query: str = "",
        limit: int = 5,
    ) -> dict[str, Any]:
        return request.app.state.runtime.match_agent_skills(
            agent_id=agent_id,
            user_message=query,
            limit=limit,
        )

    @router.post("/agents/{agent_id}/skills/reload")
    async def reload_agent_skills(agent_id: str, request: Request) -> dict[str, Any]:
        return request.app.state.runtime.reload_agent_skills(agent_id=agent_id)

    @router.get("/agents/{agent_id}/skills/template")
    async def skill_template(agent_id: str, request: Request, skill_name: str = "new_skill") -> dict[str, str]:
        del agent_id
        return {"template": request.app.state.runtime.skill_template(skill_name)}

    @router.get("/agents/{agent_id}/plugins")
    async def list_agent_plugins(agent_id: str, request: Request, force_refresh: bool = False) -> dict[str, Any]:
        return request.app.state.runtime.list_agent_plugins(agent_id=agent_id, force_refresh=force_refresh)

    @router.post("/agents/{agent_id}/plugins/reload")
    async def reload_agent_plugins(agent_id: str, request: Request) -> dict[str, Any]:
        return request.app.state.runtime.reload_agent_plugins(agent_id=agent_id)

    @router.get("/agents/{agent_id}/plugins/template")
    async def plugin_template(agent_id: str, request: Request, plugin_id: str = "new_plugin") -> dict[str, Any]:
        del agent_id
        return {"template": request.app.state.runtime.plugin_template(plugin_id)}

    @router.put("/agents/{agent_id}/plugins/{plugin_id}")
    async def install_agent_plugin(
        agent_id: str,
        plugin_id: str,
        body: PluginUpsertRequest,
        request: Request,
    ) -> dict[str, Any]:
        try:
            return request.app.state.runtime.install_agent_plugin(
                agent_id=agent_id,
                plugin_id=plugin_id,
                manifest=body.manifest,
                skills=body.skills,
            )
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/agents/{agent_id}/plugins/{plugin_id}/state")
    async def set_agent_plugin_state(
        agent_id: str,
        plugin_id: str,
        body: PluginStateRequest,
        request: Request,
    ) -> dict[str, Any]:
        try:
            return request.app.state.runtime.set_agent_plugin_enabled(
                agent_id=agent_id,
                plugin_id=plugin_id,
                enabled=body.enabled,
            )
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/agents/{agent_id}/plugins/{plugin_id}")
    async def delete_agent_plugin(agent_id: str, plugin_id: str, request: Request) -> dict[str, Any]:
        return request.app.state.runtime.delete_agent_plugin(agent_id=agent_id, plugin_id=plugin_id)

    @router.put("/agents/{agent_id}/skills/{skill_id}")
    async def upsert_agent_skill(
        agent_id: str,
        skill_id: str,
        body: SkillUpsertRequest,
        request: Request,
    ) -> dict[str, Any]:
        try:
            return request.app.state.runtime.upsert_agent_skill(
                agent_id=agent_id,
                skill_id=skill_id,
                markdown=body.markdown,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/agents/{agent_id}/skills/{skill_id}")
    async def delete_agent_skill(agent_id: str, skill_id: str, request: Request) -> dict[str, Any]:
        return request.app.state.runtime.delete_agent_skill(agent_id=agent_id, skill_id=skill_id)

    @router.post("/agents/{agent_id}/stop")
    async def stop_agent(agent_id: str, body: AgentStopRequest, request: Request) -> dict[str, Any]:
        ok, message = request.app.state.runtime.agent_manager.stop_agent(agent_id=agent_id, force=body.force)
        if not ok:
            raise HTTPException(status_code=400, detail=message)
        return {"stopped": True, "message": message}

    @router.post("/tasks/tool")
    async def create_tool_task(body: ToolTaskRequest, request: Request) -> dict[str, Any]:
        return await request.app.state.runtime.execute_tool_task(
            tool_name=body.tool_name,
            session_id=body.session_id,
            agent_id=body.agent_id,
            args=body.args,
            caller=body.caller,
            confirm=body.confirm,
        )

    @router.get("/tools")
    async def list_tools(request: Request) -> dict[str, Any]:
        return request.app.state.runtime.list_tools()

    @router.get("/tools/logs")
    async def tool_logs(request: Request, limit: int = 100, tool_name: str | None = None) -> dict[str, Any]:
        return request.app.state.runtime.tool_logs(limit=limit, tool_name=tool_name)

    @router.get("/tools/approvals")
    async def tool_approvals(request: Request, limit: int = 20) -> dict[str, Any]:
        return request.app.state.runtime.tool_approvals(limit=limit)

    @router.post("/tools/approvals/{approval_id}/approve")
    async def approve_tool_approval(approval_id: str, request: Request) -> dict[str, Any]:
        result = await request.app.state.runtime.approve_tool_approval(approval_id)
        if result is None:
            raise HTTPException(status_code=404, detail="approval not found")
        return result

    @router.post("/tools/approvals/{approval_id}/reject")
    async def reject_tool_approval(
        approval_id: str,
        body: ToolApprovalDecisionRequest,
        request: Request,
    ) -> dict[str, Any]:
        result = request.app.state.runtime.reject_tool_approval(approval_id, reason=body.reason)
        if result is None:
            raise HTTPException(status_code=404, detail="approval not found")
        return result

    @router.post("/tools/debug/execute")
    async def debug_execute_tool(body: ToolTaskRequest, request: Request) -> dict[str, Any]:
        return await request.app.state.runtime.execute_tool_task(
            tool_name=body.tool_name,
            session_id=body.session_id,
            agent_id=body.agent_id,
            args=body.args,
            caller=body.caller or "debug",
            confirm=body.confirm,
        )

    @router.post("/tasks/memory")
    async def create_memory_task(body: MemoryTaskRequest, request: Request) -> dict[str, Any]:
        return await request.app.state.runtime.execute_memory_task(
            session_id=body.session_id,
            agent_id=body.agent_id,
            entry=body.entry,
            memory_type=body.memory_type,
            importance=body.importance,
            source=body.source,
            metadata=body.metadata,
        )

    @router.get("/memory/{agent_id}/query")
    async def query_memory(
        agent_id: str,
        request: Request,
        query: str = "",
        limit: int = 20,
        memory_type: str | None = None,
        min_weight: float = 0.0,
    ) -> dict[str, Any]:
        return request.app.state.runtime.query_memory(
            agent_id=agent_id,
            query=query,
            limit=limit,
            memory_type=memory_type,
            min_weight=min_weight,
        )

    @router.post("/memory/{agent_id}/summarize")
    async def summarize_memory(agent_id: str, request: Request, max_items: int = 120) -> dict[str, Any]:
        return request.app.state.runtime.summarize_memory(agent_id=agent_id, max_items=max_items)

    @router.post("/memory/{agent_id}/compress")
    async def compress_memory(agent_id: str, request: Request) -> dict[str, Any]:
        return request.app.state.runtime.compress_memory(agent_id=agent_id)

    @router.post("/memory/{agent_id}/decay")
    async def decay_memory(agent_id: str, request: Request) -> dict[str, Any]:
        return request.app.state.runtime.decay_memory(agent_id=agent_id)

    @router.get("/dashboard/agents")
    async def dashboard_agents(request: Request) -> list[dict[str, Any]]:
        return request.app.state.runtime.dashboard_agents()

    @router.get("/dashboard/sessions")
    async def dashboard_sessions(request: Request) -> list[dict[str, Any]]:
        return request.app.state.runtime.dashboard_sessions()

    @router.get("/dashboard/logs")
    async def dashboard_logs(request: Request, limit: int = 100) -> list[dict[str, Any]]:
        return request.app.state.runtime.dashboard_logs(limit=limit)

    @router.get("/dashboard/memory/{agent_id}")
    async def dashboard_memory(agent_id: str, request: Request) -> dict[str, object]:
        return request.app.state.runtime.dashboard_memory(agent_id=agent_id)

    @router.get("/dashboard/tasks")
    async def dashboard_tasks(request: Request, limit: int = 100) -> dict[str, Any]:
        return request.app.state.runtime.dashboard_tasks(limit=limit)

    @router.get("/dashboard/models")
    async def dashboard_models(request: Request, limit: int = 100) -> dict[str, Any]:
        return request.app.state.runtime.dashboard_models(limit=limit)

    @router.get("/dashboard/tools")
    async def dashboard_tools(
        request: Request,
        limit: int = 100,
        tool_name: str | None = None,
    ) -> dict[str, Any]:
        return request.app.state.runtime.dashboard_tools(limit=limit, tool_name=tool_name)

    @router.get("/dashboard/skills/{agent_id}")
    async def dashboard_skills(
        agent_id: str,
        request: Request,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        return request.app.state.runtime.dashboard_skills(agent_id=agent_id, force_refresh=force_refresh)

    @router.get("/dashboard/workspaces")
    async def dashboard_workspaces(request: Request) -> dict[str, Any]:
        return request.app.state.runtime.dashboard_workspaces()

    @router.get("/dashboard/system")
    async def dashboard_system(request: Request) -> dict[str, Any]:
        return request.app.state.runtime.dashboard_system()

    return router
