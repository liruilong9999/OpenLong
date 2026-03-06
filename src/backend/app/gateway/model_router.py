from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings


@dataclass(slots=True)
class ModelEndpoint:
    provider: str
    base_url: str
    model: str
    reasoning_effort: str
    has_api_key: bool


class ModelRouter:
    def __init__(self, settings: Settings) -> None:
        provider = settings.model_provider or "OpenAI"
        self._default_endpoint = ModelEndpoint(
            provider=provider,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            reasoning_effort=settings.openai_reasoning_effort,
            has_api_key=bool(settings.openai_api_key),
        )

    def endpoint_for(self, agent_id: str) -> ModelEndpoint:
        # Future: map agent_id to dedicated providers/models.
        return self._default_endpoint
