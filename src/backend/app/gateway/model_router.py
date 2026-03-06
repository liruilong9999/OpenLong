from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
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
        }


class ModelRouter:
    def __init__(self, settings: Settings, event_bus: EventBus | None = None) -> None:
        provider = settings.model_provider or "OpenAI"
        self._default_endpoint = ModelEndpoint(
            provider=provider,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            reasoning_effort=settings.openai_reasoning_effort,
            has_api_key=bool(settings.openai_api_key),
        )
        self._event_bus = event_bus
        self._history: deque[ModelCallRecord] = deque(maxlen=1000)

    def endpoint_for(self, agent_id: str, task_type: str = "chat") -> ModelEndpoint:
        del agent_id
        del task_type
        # 预留：可按 agent/task 维度映射不同 provider/model。
        return self._default_endpoint

    async def dispatch(
        self,
        agent_id: str,
        task_type: str,
        prompt_preview: str,
        session_id: str = "",
    ) -> ModelCallRecord:
        endpoint = self.endpoint_for(agent_id=agent_id, task_type=task_type)
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
            "default_provider": self._default_endpoint.provider,
            "default_model": self._default_endpoint.model,
        }
