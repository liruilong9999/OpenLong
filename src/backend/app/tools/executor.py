from __future__ import annotations

from time import perf_counter
from typing import Any

from app.core.events import EventBus
from app.tools.approvals import ToolApprovalStatus, ToolApprovalStore
from app.tools.builtins.shell_tool import classify_shell_command
from app.tools.logger import ToolExecutionLogStore
from app.tools.permissions import ToolPermissionManager
from app.tools.registry import ToolRegistry
from app.tools.sandbox import ToolSandbox
from app.tools.types import ToolCall, ToolExecutionRecord, ToolResult


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        event_bus: EventBus | None = None,
        permission_manager: ToolPermissionManager | None = None,
        sandbox: ToolSandbox | None = None,
        log_store: ToolExecutionLogStore | None = None,
        approval_store: ToolApprovalStore | None = None,
    ) -> None:
        self._registry = registry
        self._event_bus = event_bus
        self._permission_manager = permission_manager or ToolPermissionManager()
        self._sandbox = sandbox or ToolSandbox()
        self._log_store = log_store or ToolExecutionLogStore()
        self._approval_store = approval_store or ToolApprovalStore()

    async def execute_call(self, call: ToolCall) -> ToolResult:
        return await self.execute(
            call.tool_name,
            caller=call.caller,
            confirm=call.confirm,
            require_confirmation=call.require_confirmation,
            session_id=call.session_id,
            agent_id=call.agent_id,
            **call.args,
        )

    async def execute(self, tool_name: str, **kwargs: Any) -> ToolResult:
        started = perf_counter()
        caller = str(kwargs.pop("caller", "agent"))
        confirm = bool(kwargs.pop("confirm", False))
        kwargs.pop("require_confirmation", None)
        session_id = str(kwargs.get("session_id", ""))
        agent_id = str(kwargs.get("agent_id", "main"))

        allowed, deny_reason = self._permission_manager.is_allowed(tool_name)
        if not allowed:
            result = ToolResult(success=False, content=deny_reason or "tool blocked")
            latency_ms = round((perf_counter() - started) * 1000, 3)
            record = self._record(
                tool_name=tool_name,
                session_id=session_id,
                agent_id=agent_id,
                caller=caller,
                args=kwargs,
                result=result,
                latency_ms=latency_ms,
                denied_reason=deny_reason,
            )
            self._attach_trace(result, record)
            self._emit("tool.execution.denied", tool_name, session_id, agent_id, result.success, deny_reason, latency_ms)
            return result

        tool = self._registry.get(tool_name)
        if tool is None:
            result = ToolResult(success=False, content=f"tool not found: {tool_name}")
            latency_ms = round((perf_counter() - started) * 1000, 3)
            record = self._record(
                tool_name=tool_name,
                session_id=session_id,
                agent_id=agent_id,
                caller=caller,
                args=kwargs,
                result=result,
                latency_ms=latency_ms,
                denied_reason=None,
            )
            self._attach_trace(result, record)
            self._emit("tool.execution.completed", tool_name, session_id, agent_id, result.success, None, latency_ms)
            return result

        valid, validation_reason = self._validate_parameters(tool_name=tool_name, kwargs=kwargs)
        if not valid:
            result = ToolResult(success=False, content=validation_reason or "invalid tool arguments")
            latency_ms = round((perf_counter() - started) * 1000, 3)
            record = self._record(
                tool_name=tool_name,
                session_id=session_id,
                agent_id=agent_id,
                caller=caller,
                args=kwargs,
                result=result,
                latency_ms=latency_ms,
                denied_reason=validation_reason,
            )
            self._attach_trace(result, record)
            self._emit("tool.execution.denied", tool_name, session_id, agent_id, result.success, validation_reason, latency_ms)
            return result

        sandbox_ok, sandbox_reason, safe_kwargs = self._sandbox.validate(tool_name, kwargs)
        if not sandbox_ok:
            result = ToolResult(success=False, content=sandbox_reason or "tool blocked by sandbox")
            latency_ms = round((perf_counter() - started) * 1000, 3)
            record = self._record(
                tool_name=tool_name,
                session_id=session_id,
                agent_id=agent_id,
                caller=caller,
                args=kwargs,
                result=result,
                latency_ms=latency_ms,
                denied_reason=sandbox_reason,
            )
            self._attach_trace(result, record)
            self._emit("tool.execution.denied", tool_name, session_id, agent_id, result.success, sandbox_reason, latency_ms)
            return result

        if self._permission_manager.requires_confirmation(tool_name) and caller != "system" and not confirm:
            if tool_name == "shell":
                approval = self._approval_store.create(
                    tool_name=tool_name,
                    session_id=session_id,
                    agent_id=agent_id,
                    caller=caller,
                    args=safe_kwargs,
                    command_preview=str(safe_kwargs.get("input", "")).strip(),
                    category=classify_shell_command(str(safe_kwargs.get("input", "")).strip()),
                )
                result = ToolResult(
                    success=False,
                    content=f"shell command awaiting approval: {approval.approval_id}",
                    data={"pending_approval": True, "approval": approval.to_dict()},
                )
                latency_ms = round((perf_counter() - started) * 1000, 3)
                record = self._record(
                    tool_name=tool_name,
                    session_id=session_id,
                    agent_id=agent_id,
                    caller=caller,
                    args=safe_kwargs,
                    result=result,
                    latency_ms=latency_ms,
                    denied_reason="approval pending",
                )
                self._attach_trace(result, record)
                self._emit(
                    "tool.approval.created",
                    tool_name,
                    session_id,
                    agent_id,
                    False,
                    None,
                    latency_ms,
                    extra_payload={
                        "approval_id": approval.approval_id,
                        "category": approval.category,
                        "command_preview": approval.command_preview,
                    },
                )
                return result

            result = ToolResult(success=False, content=f"tool requires confirmation: {tool_name}")
            latency_ms = round((perf_counter() - started) * 1000, 3)
            record = self._record(
                tool_name=tool_name,
                session_id=session_id,
                agent_id=agent_id,
                caller=caller,
                args=safe_kwargs,
                result=result,
                latency_ms=latency_ms,
                denied_reason=f"tool requires confirmation: {tool_name}",
            )
            self._attach_trace(result, record)
            self._emit("tool.execution.denied", tool_name, session_id, agent_id, result.success, f"tool requires confirmation: {tool_name}", latency_ms)
            return result

        execution_kwargs = dict(safe_kwargs)
        if tool_name == "shell":
            execution_kwargs = {
                **safe_kwargs,
                "stream_handler": self._build_shell_stream_handler(session_id=session_id, agent_id=agent_id, tool_name=tool_name),
            }

        result = await tool.run(**execution_kwargs)
        latency_ms = round((perf_counter() - started) * 1000, 3)
        record = self._record(
            tool_name=tool_name,
            session_id=session_id,
            agent_id=agent_id,
            caller=caller,
            args=safe_kwargs,
            result=result,
            latency_ms=latency_ms,
            denied_reason=None,
        )
        self._attach_trace(result, record)
        self._emit("tool.execution.completed", tool_name, session_id, agent_id, result.success, None, latency_ms)
        return result

    async def approve(self, approval_id: str) -> dict[str, Any] | None:
        approval = self._approval_store.get(approval_id)
        if approval is None or approval.status != ToolApprovalStatus.PENDING:
            return None

        self._emit(
            "tool.approval.approved",
            approval.tool_name,
            approval.session_id,
            approval.agent_id,
            True,
            None,
            0.0,
            extra_payload={"approval_id": approval.approval_id, "category": approval.category},
        )
        result = await self.execute(
            approval.tool_name,
            **{**approval.args, "caller": approval.caller, "confirm": True},
        )
        resolved = self._approval_store.resolve(
            approval_id,
            success=result.success,
            result={"content": result.content, "data": result.data},
            reason=None,
        )
        return resolved.to_dict() if resolved is not None else None

    def reject(self, approval_id: str, reason: str = "manual reject") -> dict[str, Any] | None:
        approval = self._approval_store.reject(approval_id, reason=reason)
        if approval is None:
            return None
        self._emit(
            "tool.approval.rejected",
            approval.tool_name,
            approval.session_id,
            approval.agent_id,
            False,
            reason,
            0.0,
            extra_payload={"approval_id": approval.approval_id, "category": approval.category},
        )
        return approval.to_dict()

    def approval_snapshot(self, limit: int = 20) -> dict[str, Any]:
        return {
            "stats": self._approval_store.stats(),
            "items": self._approval_store.list(status=ToolApprovalStatus.PENDING, limit=limit),
            "recent": self._approval_store.list(limit=limit),
        }

    def prompt_tool_catalog(self) -> list[dict[str, Any]]:
        specs = self._registry.list_specs()
        allowed_tools = set(self.permission_snapshot()["allowlist"])
        confirmation_required = set(self.permission_snapshot()["confirmation_required"])
        items: list[dict[str, Any]] = []
        for spec in specs:
            if allowed_tools and spec.name not in allowed_tools:
                continue
            payload = spec.to_dict()
            payload["requires_confirmation"] = spec.name in confirmation_required
            items.append(payload)
        return items

    def recent_logs(self, limit: int = 100, tool_name: str | None = None) -> list[dict[str, Any]]:
        return self._log_store.recent(limit=limit, tool_name=tool_name)

    def log_stats(self) -> dict[str, Any]:
        return self._log_store.stats()

    def permission_snapshot(self) -> dict[str, Any]:
        return {
            "profile": self._permission_manager.profile,
            "allowlist": sorted(self._permission_manager.allowlist or set()),
            "denylist": sorted(self._permission_manager.denylist or set()),
            "confirmation_required": sorted(self._permission_manager.confirmation_required or set()),
        }

    def _validate_parameters(self, tool_name: str, kwargs: dict[str, Any]) -> tuple[bool, str | None]:
        tool = self._registry.get(tool_name)
        if tool is None:
            return False, f"tool not found: {tool_name}"

        spec = tool.spec
        for param in spec.parameters:
            value = kwargs.get(param.name)
            if param.required and value in (None, ""):
                return False, f"missing required parameter: {param.name}"
            if value in (None, ""):
                continue
            if param.param_type == "number":
                try:
                    float(value)
                except (TypeError, ValueError):
                    return False, f"parameter {param.name} must be a number"
            elif param.param_type in {"bool", "boolean"} and not isinstance(value, bool):
                return False, f"parameter {param.name} must be a boolean"
            elif param.param_type == "object" and not isinstance(value, dict):
                return False, f"parameter {param.name} must be an object"
            elif param.param_type == "array" and not isinstance(value, list):
                return False, f"parameter {param.name} must be an array"
        return True, None

    def _record(
        self,
        *,
        tool_name: str,
        session_id: str,
        agent_id: str,
        caller: str,
        args: dict[str, Any],
        result: ToolResult,
        latency_ms: float,
        denied_reason: str | None,
    ) -> ToolExecutionRecord:
        record = ToolExecutionRecord.create(
            tool_name=tool_name,
            session_id=session_id,
            agent_id=agent_id,
            caller=caller,
            args=args,
            success=result.success,
            latency_ms=latency_ms,
            result_preview=result.content[:500],
            result_data=dict(result.data),
            denied_reason=denied_reason,
        )
        self._log_store.append(record)
        return record

    def _attach_trace(self, result: ToolResult, record: ToolExecutionRecord) -> None:
        result.data = {**result.data, "trace": record.to_dict()}

    def _build_shell_stream_handler(self, *, session_id: str, agent_id: str, tool_name: str):
        async def _handler(*, stream: str, text: str) -> None:
            self._emit(
                "tool.execution.stream",
                tool_name,
                session_id,
                agent_id,
                True,
                None,
                0.0,
                extra_payload={"stream": stream, "text": text},
            )

        return _handler

    def _emit(
        self,
        event_name: str,
        tool_name: str,
        session_id: str,
        agent_id: str,
        success: bool,
        denied_reason: str | None,
        latency_ms: float,
        extra_payload: dict[str, Any] | None = None,
    ) -> None:
        if self._event_bus is None:
            return
        self._event_bus.emit(
            event_name,
            {
                "session_id": session_id,
                "agent_id": agent_id,
                "tool_name": tool_name,
                "success": success,
                "latency_ms": latency_ms,
                "denied_reason": denied_reason,
                **(extra_payload or {}),
            },
        )

