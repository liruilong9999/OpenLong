from __future__ import annotations

from time import perf_counter
from typing import Any

from app.core.events import EventBus
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
    ) -> None:
        self._registry = registry
        self._event_bus = event_bus
        self._permission_manager = permission_manager or ToolPermissionManager()
        self._sandbox = sandbox or ToolSandbox()
        self._log_store = log_store or ToolExecutionLogStore()

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

        allowed, deny_reason = self._permission_manager.authorize(
            tool_name=tool_name,
            caller=caller,
            confirm=confirm,
        )
        if not allowed:
            result = ToolResult(success=False, content=deny_reason or "tool blocked")
            latency_ms = round((perf_counter() - started) * 1000, 3)
            self._record(
                tool_name=tool_name,
                session_id=session_id,
                agent_id=agent_id,
                caller=caller,
                args=kwargs,
                result=result,
                latency_ms=latency_ms,
                denied_reason=deny_reason,
            )
            self._emit("tool.execution.denied", tool_name, session_id, agent_id, result.success, deny_reason, latency_ms)
            return result

        tool = self._registry.get(tool_name)
        if tool is None:
            result = ToolResult(success=False, content=f"tool not found: {tool_name}")
            latency_ms = round((perf_counter() - started) * 1000, 3)
            self._record(
                tool_name=tool_name,
                session_id=session_id,
                agent_id=agent_id,
                caller=caller,
                args=kwargs,
                result=result,
                latency_ms=latency_ms,
                denied_reason=None,
            )
            self._emit("tool.execution.completed", tool_name, session_id, agent_id, result.success, None, latency_ms)
            return result

        valid, validation_reason = self._validate_parameters(tool_name=tool_name, kwargs=kwargs)
        if not valid:
            result = ToolResult(success=False, content=validation_reason or "invalid tool arguments")
            latency_ms = round((perf_counter() - started) * 1000, 3)
            self._record(
                tool_name=tool_name,
                session_id=session_id,
                agent_id=agent_id,
                caller=caller,
                args=kwargs,
                result=result,
                latency_ms=latency_ms,
                denied_reason=validation_reason,
            )
            self._emit("tool.execution.denied", tool_name, session_id, agent_id, result.success, validation_reason, latency_ms)
            return result

        sandbox_ok, sandbox_reason, safe_kwargs = self._sandbox.validate(tool_name, kwargs)
        if not sandbox_ok:
            result = ToolResult(success=False, content=sandbox_reason or "tool blocked by sandbox")
            latency_ms = round((perf_counter() - started) * 1000, 3)
            self._record(
                tool_name=tool_name,
                session_id=session_id,
                agent_id=agent_id,
                caller=caller,
                args=kwargs,
                result=result,
                latency_ms=latency_ms,
                denied_reason=sandbox_reason,
            )
            self._emit("tool.execution.denied", tool_name, session_id, agent_id, result.success, sandbox_reason, latency_ms)
            return result

        result = await tool.run(**safe_kwargs)
        latency_ms = round((perf_counter() - started) * 1000, 3)
        self._record(
            tool_name=tool_name,
            session_id=session_id,
            agent_id=agent_id,
            caller=caller,
            args=safe_kwargs,
            result=result,
            latency_ms=latency_ms,
            denied_reason=None,
        )
        self._emit("tool.execution.completed", tool_name, session_id, agent_id, result.success, None, latency_ms)
        return result

    def recent_logs(self, limit: int = 100, tool_name: str | None = None) -> list[dict[str, Any]]:
        return self._log_store.recent(limit=limit, tool_name=tool_name)

    def log_stats(self) -> dict[str, Any]:
        return self._log_store.stats()

    def permission_snapshot(self) -> dict[str, Any]:
        return {
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
    ) -> None:
        record = ToolExecutionRecord.create(
            tool_name=tool_name,
            session_id=session_id,
            agent_id=agent_id,
            caller=caller,
            args=args,
            success=result.success,
            latency_ms=latency_ms,
            result_preview=result.content[:500],
            denied_reason=denied_reason,
        )
        self._log_store.append(record)

    def _emit(
        self,
        event_name: str,
        tool_name: str,
        session_id: str,
        agent_id: str,
        success: bool,
        denied_reason: str | None,
        latency_ms: float,
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
            },
        )

