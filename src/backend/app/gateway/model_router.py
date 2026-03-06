from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Callable
from uuid import uuid4

from app.core.config import Settings
from app.core.events import EventBus


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class ModelEndpoint:
    provider: str
    base_url: str
    model: str
    reasoning_effort: str
    has_api_key: bool
    api_key: str = field(default="", repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "has_api_key": self.has_api_key,
        }


@dataclass(slots=True)
class ModelRoute:
    source: str
    agent_id: str
    task_type: str
    endpoints: list[ModelEndpoint]

    def primary(self) -> ModelEndpoint:
        return self.endpoints[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "agent_id": self.agent_id,
            "task_type": self.task_type,
            "endpoints": [item.to_dict() for item in self.endpoints],
        }


@dataclass(slots=True)
class ModelCallRecord:
    call_id: str
    agent_id: str
    task_type: str
    provider: str
    model: str
    success: bool
    latency_ms: float
    timestamp: datetime = field(default_factory=_utc_now)
    error: str | None = None
    route_source: str = "default"
    endpoint_index: int = 0
    is_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "agent_id": self.agent_id,
            "task_type": self.task_type,
            "provider": self.provider,
            "model": self.model,
            "success": self.success,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp.isoformat(),
            "error": self.error,
            "route_source": self.route_source,
            "endpoint_index": self.endpoint_index,
            "is_fallback": self.is_fallback,
        }


class ModelRouter:
    def __init__(self, settings: Settings, event_bus: EventBus | None = None) -> None:
        self._event_bus = event_bus
        self._history: deque[ModelCallRecord] = deque(maxlen=1000)
        self._default_endpoint = self._default_from_settings(settings)
        self._config_source = self._resolve_config_source(settings)
        self._config_error: str | None = None
        self._routes = self._parse_routes(self._config_source)

    def route_for(self, agent_id: str, task_type: str = "chat") -> ModelRoute:
        task_key = (task_type or "chat").strip().lower() or "chat"
        agent_key = (agent_id or "main").strip() or "main"

        agent_routes = self._routes.get("agents", {}).get(agent_key, {})
        agent_task_routes = agent_routes.get("tasks", {}) if isinstance(agent_routes, dict) else {}
        global_task_routes = self._routes.get("tasks", {})

        candidates = [
            (f"agent:{agent_key}/task:{task_key}", agent_task_routes.get(task_key)),
            (f"agent:{agent_key}/task:*", agent_task_routes.get("*")),
            (f"agent:{agent_key}/default", agent_routes.get("defaults") if isinstance(agent_routes, dict) else None),
            (f"task:{task_key}", global_task_routes.get(task_key)),
            ("task:*", global_task_routes.get("*")),
            ("default", self._routes.get("defaults")),
        ]

        for source, payload in candidates:
            endpoints = self._endpoints_from_payload(payload, source=source)
            if endpoints:
                return ModelRoute(source=source, agent_id=agent_key, task_type=task_key, endpoints=endpoints)

        return ModelRoute(source="settings-default", agent_id=agent_key, task_type=task_key, endpoints=[self._default_endpoint])

    def endpoint_for(self, agent_id: str, task_type: str = "chat") -> ModelEndpoint:
        return self.route_for(agent_id=agent_id, task_type=task_type).primary()

    def route_request_payload(self, agent_id: str, task_type: str = "chat") -> dict[str, Any]:
        route = self.route_for(agent_id=agent_id, task_type=task_type)
        return {
            "source": route.source,
            "endpoints": [
                {
                    "provider": item.provider,
                    "base_url": item.base_url,
                    "model": item.model,
                    "reasoning_effort": item.reasoning_effort,
                    "api_key": item.api_key,
                    "has_api_key": item.has_api_key,
                }
                for item in route.endpoints
            ],
        }

    def attempt_observer(
        self,
        *,
        agent_id: str,
        task_type: str,
        session_id: str,
        route_source: str,
    ) -> Callable[..., None]:
        def _record_attempt(
            *,
            provider: str,
            model: str,
            success: bool,
            latency_ms: float,
            error: str | None,
            endpoint_index: int,
        ) -> None:
            record = ModelCallRecord(
                call_id=str(uuid4()),
                agent_id=agent_id,
                task_type=task_type,
                provider=provider,
                model=model,
                success=success,
                latency_ms=latency_ms,
                error=error,
                route_source=route_source,
                endpoint_index=endpoint_index,
                is_fallback=endpoint_index > 0,
            )
            self._history.append(record)

            if self._event_bus is not None:
                self._event_bus.emit(
                    "model.call.completed",
                    {
                        "session_id": session_id,
                        "agent_id": agent_id,
                        "task_type": task_type,
                        "provider": provider,
                        "model": model,
                        "success": success,
                        "error": error,
                        "route_source": route_source,
                        "endpoint_index": endpoint_index,
                        "is_fallback": endpoint_index > 0,
                    },
                )

        return _record_attempt

    async def dispatch(
        self,
        agent_id: str,
        task_type: str,
        prompt_preview: str,
        session_id: str = "",
    ) -> ModelCallRecord:
        route = self.route_for(agent_id=agent_id, task_type=task_type)
        endpoint = route.primary()
        started = perf_counter()

        del prompt_preview
        success = endpoint.has_api_key
        error = None if success else "API key missing, dispatch recorded only"

        record = ModelCallRecord(
            call_id=str(uuid4()),
            agent_id=agent_id,
            task_type=task_type,
            provider=endpoint.provider,
            model=endpoint.model,
            success=success,
            latency_ms=round((perf_counter() - started) * 1000, 3),
            error=error,
            route_source=route.source,
            endpoint_index=0,
            is_fallback=False,
        )
        self._history.append(record)

        if self._event_bus is not None:
            self._event_bus.emit(
                "model.call.completed",
                {
                    "session_id": session_id,
                    "agent_id": agent_id,
                    "task_type": task_type,
                    "provider": endpoint.provider,
                    "model": endpoint.model,
                    "success": success,
                    "error": error,
                    "route_source": route.source,
                    "endpoint_index": 0,
                    "is_fallback": False,
                },
            )

        return record

    def recent_calls(self, limit: int = 100) -> list[dict[str, Any]]:
        return [item.to_dict() for item in list(self._history)[-limit:]][::-1]

    def stats(self) -> dict[str, Any]:
        calls = list(self._history)
        return {
            "total": len(calls),
            "success": sum(1 for item in calls if item.success),
            "failed": sum(1 for item in calls if not item.success),
            "fallback_activations": sum(1 for item in calls if item.success and item.is_fallback),
            "default_provider": self._default_endpoint.provider,
            "default_model": self._default_endpoint.model,
            "config_error": self._config_error,
        }

    def route_snapshot(self) -> dict[str, Any]:
        return {
            "config_source": self._config_source["type"],
            "config_error": self._config_error,
            "effective_default": self._default_endpoint.to_dict(),
            "defaults": [item.to_dict() for item in self._endpoints_from_payload(self._routes.get("defaults"), source="default")],
            "tasks": {
                key: [item.to_dict() for item in self._endpoints_from_payload(value, source=f"task:{key}")]
                for key, value in sorted(self._routes.get("tasks", {}).items())
            },
            "agents": {
                agent_id: {
                    "defaults": [
                        item.to_dict()
                        for item in self._endpoints_from_payload(payload.get("defaults"), source=f"agent:{agent_id}/default")
                    ],
                    "tasks": {
                        task_key: [
                            item.to_dict()
                            for item in self._endpoints_from_payload(task_payload, source=f"agent:{agent_id}/task:{task_key}")
                        ]
                        for task_key, task_payload in sorted((payload.get("tasks") or {}).items())
                    },
                }
                for agent_id, payload in sorted(self._routes.get("agents", {}).items())
                if isinstance(payload, dict)
            },
        }

    def _default_from_settings(self, settings: Settings) -> ModelEndpoint:
        provider = getattr(settings, "model_provider", "") or "OpenAI"
        base_url = getattr(settings, "openai_base_url", "") or ""
        model = getattr(settings, "openai_model", "") or ""
        reasoning_effort = getattr(settings, "openai_reasoning_effort", "") or "medium"
        api_key = getattr(settings, "openai_api_key", "") or ""
        return ModelEndpoint(
            provider=provider,
            base_url=base_url,
            model=model,
            reasoning_effort=reasoning_effort,
            has_api_key=bool(api_key),
            api_key=api_key,
        )

    def _resolve_config_source(self, settings: Settings) -> dict[str, str]:
        inline = str(getattr(settings, "model_routes", "") or "").strip()
        if inline:
            return {"type": "inline", "value": inline}

        configured_path = str(getattr(settings, "model_routes_path", "") or "").strip()
        if not configured_path:
            return {"type": "default", "value": ""}

        candidates = [Path(configured_path)]
        if not Path(configured_path).is_absolute():
            repo_root = Path(__file__).resolve().parents[4]
            candidates.append(Path.cwd() / configured_path)
            candidates.append(repo_root / configured_path)

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return {"type": str(candidate.resolve()), "value": candidate.read_text(encoding="utf-8")}

        self._config_error = f"model routes file not found: {configured_path}"
        return {"type": f"missing:{configured_path}", "value": ""}

    def _parse_routes(self, config_source: dict[str, str]) -> dict[str, Any]:
        raw = str(config_source.get("value") or "").strip()
        if not raw:
            return {"defaults": [], "tasks": {}, "agents": {}}

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._config_error = f"invalid model route config: {exc}"
            return {"defaults": [], "tasks": {}, "agents": {}}

        if not isinstance(payload, dict):
            self._config_error = "invalid model route config: root must be an object"
            return {"defaults": [], "tasks": {}, "agents": {}}

        return {
            "defaults": payload.get("defaults") or [],
            "tasks": payload.get("tasks") or {},
            "agents": payload.get("agents") or {},
        }

    def _endpoints_from_payload(self, payload: Any, *, source: str) -> list[ModelEndpoint]:
        if not isinstance(payload, list):
            return []

        endpoints: list[ModelEndpoint] = []
        for item in payload:
            endpoint = self._endpoint_from_item(item, source=source)
            if endpoint is not None:
                endpoints.append(endpoint)
        return endpoints

    def _endpoint_from_item(self, payload: Any, *, source: str) -> ModelEndpoint | None:
        if not isinstance(payload, dict):
            return None
        if payload.get("enabled") is False:
            return None

        provider = str(payload.get("provider") or self._default_endpoint.provider or "OpenAI")
        base_url = str(payload.get("base_url") or self._default_endpoint.base_url or "")
        model = str(payload.get("model") or self._default_endpoint.model or "")
        reasoning_effort = str(payload.get("reasoning_effort") or self._default_endpoint.reasoning_effort or "medium")
        api_key = str(payload.get("api_key") or self._default_endpoint.api_key or "")

        if not model:
            self._config_error = f"model route endpoint missing model in {source}"
            return None

        return ModelEndpoint(
            provider=provider,
            base_url=base_url,
            model=model,
            reasoning_effort=reasoning_effort,
            has_api_key=bool(api_key),
            api_key=api_key,
        )
