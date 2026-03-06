from types import SimpleNamespace

from app.agent.model_client import HeuristicModelClient, ModelRequest, OpenAICompatibleModelClient


def test_openai_model_client_falls_back_when_missing_key() -> None:
    settings = SimpleNamespace(
        model_provider="OpenAI",
        openai_base_url="",
        openai_model="gpt-5.3",
        openai_api_key="",
        openai_reasoning_effort="medium",
    )
    client = OpenAICompatibleModelClient.from_settings(settings, fallback=HeuristicModelClient())
    output = __import__('asyncio').run(
        client.generate(
            ModelRequest(
                agent_id="main",
                task_id="t1",
                user_message="你好",
                prompt="[USER]\n你好",
                iteration=0,
            )
        )
    )
    assert output.text
    assert output.metadata["mode"] == "missing_model_config"
