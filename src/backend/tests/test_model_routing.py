import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.agent.model_client import ModelRequest, OpenAICompatibleModelClient
from app.core.config import load_settings
from app.gateway.model_router import ModelRouter
from app.main import create_app


def _settings(model_routes: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        model_provider="OpenAI",
        openai_base_url="https://default.example/v1",
        openai_model="gpt-default",
        openai_reasoning_effort="medium",
        openai_api_key="sk-default",
        model_routes=model_routes,
        model_routes_path="",
    )


def test_model_router_resolves_agent_task_and_fallback_routes() -> None:
    router = ModelRouter(
        _settings(
            json.dumps(
                {
                    "defaults": [{"model": "gpt-default"}],
                    "tasks": {"summary": [{"model": "gpt-summary"}]},
                    "agents": {
                        "coder": {
                            "defaults": [{"model": "gpt-coder-default"}],
                            "tasks": {
                                "coding": [
                                    {"model": "gpt-coder-primary", "api_key": "sk-primary"},
                                    {"model": "gpt-coder-fallback", "api_key": "sk-fallback"},
                                ]
                            },
                        }
                    },
                }
            )
        )
    )

    summary_route = router.route_for(agent_id="main", task_type="summary")
    assert summary_route.source == "task:summary"
    assert summary_route.primary().model == "gpt-summary"

    coder_default = router.route_for(agent_id="coder", task_type="chat")
    assert coder_default.source == "agent:coder/default"
    assert coder_default.primary().model == "gpt-coder-default"

    coder_coding = router.route_for(agent_id="coder", task_type="coding")
    assert coder_coding.source == "agent:coder/task:coding"
    assert [item.model for item in coder_coding.endpoints] == ["gpt-coder-primary", "gpt-coder-fallback"]

    snapshot = router.route_snapshot()
    assert snapshot["effective_default"]["model"] == "gpt-default"
    assert snapshot["tasks"]["summary"][0]["model"] == "gpt-summary"
    assert snapshot["agents"]["coder"]["tasks"]["coding"][1]["model"] == "gpt-coder-fallback"


def test_model_client_uses_fallback_route(monkeypatch) -> None:
    attempts: list[tuple[str, int, bool]] = []

    async def fake_responses(self, request, *, endpoint):
        if endpoint["model"] == "gpt-primary":
            raise RuntimeError("primary unavailable")
        return f"reply from {endpoint['model']}"

    client = OpenAICompatibleModelClient(
        provider="OpenAI",
        base_url="https://default.example/v1",
        model="gpt-default",
        api_key="sk-default",
    )
    monkeypatch.setattr("app.agent.model_client._model_api_disabled", lambda: False)
    monkeypatch.setattr(OpenAICompatibleModelClient, "_responses_api", fake_responses)

    output = __import__("asyncio").run(
        client.generate(
            ModelRequest(
                agent_id="coder",
                task_id="t-route",
                task_type="coding",
                user_message="修复这个 bug",
                prompt="[USER]\n修复这个 bug",
                iteration=0,
                model_routes=[
                    {"provider": "OpenAI", "base_url": "https://primary.example/v1", "model": "gpt-primary", "api_key": "sk-1"},
                    {"provider": "OpenAI", "base_url": "https://fallback.example/v1", "model": "gpt-fallback", "api_key": "sk-2"},
                ],
                model_route_source="agent:coder/task:coding",
                attempt_observer=lambda **kwargs: attempts.append((kwargs["model"], kwargs["endpoint_index"], kwargs["success"])),
            )
        )
    )

    assert output.text == "reply from gpt-fallback"
    assert output.metadata["route_source"] == "agent:coder/task:coding"
    assert output.metadata["endpoint_index"] == 1
    assert attempts == [("gpt-primary", 0, False), ("gpt-fallback", 1, True)]


def test_dashboard_models_shows_route_and_fallback_history(monkeypatch, tmp_path) -> None:
    load_settings.cache_clear()
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv(
        "MODEL_ROUTES",
        json.dumps(
            {
                "defaults": [{"model": "gpt-default", "api_key": "sk-default"}],
                "tasks": {"summary": [{"model": "gpt-summary", "api_key": "sk-summary"}]},
                "agents": {
                    "coder": {
                        "tasks": {
                            "coding": [
                                {"model": "gpt-coder-primary", "api_key": "sk-primary"},
                                {"model": "gpt-coder-fallback", "api_key": "sk-fallback"},
                            ]
                        }
                    }
                },
            }
        ),
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-default")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://default.example/v1")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-default")
    monkeypatch.setenv("MODEL_PROVIDER", "OpenAI")
    monkeypatch.setenv("OPENLONG_DISABLE_MODEL_API", "0")
    monkeypatch.setattr("app.agent.model_client._model_api_disabled", lambda: False)

    async def fake_responses(self, request, *, endpoint):
        if endpoint["model"] == "gpt-coder-primary":
            raise RuntimeError("primary down")
        return f"ok:{endpoint['model']}"

    monkeypatch.setattr(OpenAICompatibleModelClient, "_responses_api", fake_responses)

    with TestClient(create_app()) as client:
        create_resp = client.post("/sessions", json={"session_id": "route-s1", "agent_id": "coder"})
        assert create_resp.status_code == 200

        chat_resp = client.post(
            "/chat",
            json={"session_id": "route-s1", "agent_id": "coder", "message": "请帮我修复这个 bug"},
        )
        assert chat_resp.status_code == 200

        models_resp = client.get("/dashboard/models")
        assert models_resp.status_code == 200
        payload = models_resp.json()
        assert payload["stats"]["fallback_activations"] >= 1
        assert payload["routes"]["agents"]["coder"]["tasks"]["coding"][0]["model"] == "gpt-coder-primary"
        assert payload["routes"]["agents"]["coder"]["tasks"]["coding"][1]["model"] == "gpt-coder-fallback"
        assert payload["calls"][0]["model"] == "gpt-coder-fallback"
        assert payload["calls"][0]["is_fallback"] is True
        assert payload["calls"][0]["route_source"] == "agent:coder/task:coding"
        assert payload["calls"][1]["model"] == "gpt-coder-primary"
        assert payload["calls"][1]["success"] is False

