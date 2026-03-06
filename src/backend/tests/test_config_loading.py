from pathlib import Path

from app.core.config import Settings, _hydrate_from_key_file


def test_key_file_overrides_default_model_settings(tmp_path: Path) -> None:
    key_file = tmp_path / "key.txt"
    key_file.write_text(
        "\n".join(
            [
                'name = "OpenAI"',
                'base_url = "https://example.com"',
                'model = "gpt-test-model"',
                'model_reasoning_effort = "high"',
                '"OPENAI_API_KEY": "sk-test"',
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(key_file_path=str(key_file))
    hydrated = _hydrate_from_key_file(settings)

    assert hydrated.model_provider == "OpenAI"
    assert hydrated.openai_base_url == "https://example.com"
    assert hydrated.openai_model == "gpt-test-model"
    assert hydrated.openai_reasoning_effort == "high"
    assert hydrated.openai_api_key == "sk-test"
