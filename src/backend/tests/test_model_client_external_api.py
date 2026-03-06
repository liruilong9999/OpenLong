from pathlib import Path
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
    output = __import__("asyncio").run(
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


def test_openai_model_client_attachment_content_for_image(tmp_path: Path) -> None:
    image_path = tmp_path / "demo.png"
    image_path.write_bytes(b"fake-png-bytes")

    client = OpenAICompatibleModelClient(
        provider="OpenAI",
        base_url="https://example.com",
        model="gpt-5.3",
        api_key="sk-test",
    )

    content = client._attachment_content(
        [
            {
                "filename": "demo.png",
                "relative_path": "uploads/s1/demo.png",
                "absolute_path": str(image_path),
                "content_type": "image/png",
                "size": image_path.stat().st_size,
            }
        ]
    )

    assert len(content) == 2
    assert content[0]["type"] == "input_text"
    assert content[1]["type"] == "input_image"
    assert str(content[1]["image_url"]).startswith("data:image/png;base64,")
