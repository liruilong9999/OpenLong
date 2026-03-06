from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
import re

from pydantic import BaseModel, Field

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    SettingsConfigDict = dict

    class BaseSettings(BaseModel):
        def __init__(self, **data):
            merged = _load_env_values(self.__class__)
            merged.update(data)
            super().__init__(**merged)


_KEY_LINE = re.compile(r'^\s*"?([A-Za-z0-9_]+)"?\s*(=|:)\s*"?(.+?)"?\s*$')
DEFAULT_OPENAI_MODEL = "gpt-5.3"
DEFAULT_OPENAI_REASONING_EFFORT = "medium"


def _load_env_values(settings_cls: type[BaseModel]) -> dict[str, str]:
    values: dict[str, str] = {}
    model_config = getattr(settings_cls, "model_config", {}) or {}

    env_file = model_config.get("env_file")
    env_encoding = model_config.get("env_file_encoding", "utf-8")
    case_sensitive = bool(model_config.get("case_sensitive", False))

    if env_file:
        env_path = Path(env_file)
        if env_path.exists():
            for line in env_path.read_text(encoding=env_encoding).splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, raw_value = stripped.split("=", maxsplit=1)
                env_key = key.strip()
                env_value = raw_value.strip().strip('"')
                values[env_key if case_sensitive else env_key.lower()] = env_value

    for key, value in os.environ.items():
        values[key if case_sensitive else key.lower()] = value

    resolved: dict[str, str] = {}
    annotations = getattr(settings_cls, "__annotations__", {})
    for field_name in annotations:
        field_lookup = field_name if case_sensitive else field_name.lower()
        upper_lookup = field_name.upper() if not case_sensitive else field_name
        if field_lookup in values:
            resolved[field_name] = values[field_lookup]
        elif upper_lookup in values:
            resolved[field_name] = values[upper_lookup]

    return resolved


class Settings(BaseSettings):
    app_name: str = Field(default="OpenLong")
    environment: str = Field(default="development")

    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)

    # key 文件路径，默认读取仓库内 doc/key.txt。
    key_file_path: str = Field(default="doc/key.txt")

    model_provider: str = Field(default="")
    openai_base_url: str = Field(default="")
    openai_model: str = Field(default=DEFAULT_OPENAI_MODEL)
    openai_reasoning_effort: str = Field(default=DEFAULT_OPENAI_REASONING_EFFORT)
    openai_api_key: str = Field(default="")
    model_routes: str = Field(default="")
    model_routes_path: str = Field(default="")

    workspace_root: str = Field(default="workspace")
    tool_profile: str = Field(default="coding")
    tool_shell_enabled: bool = Field(default=False)
    tool_allowlist: str = Field(default="")
    tool_denylist: str = Field(default="")
    tool_confirmation_required: str = Field(default="shell")
    tool_log_limit: int = Field(default=5000)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


def _candidate_key_paths(configured_path: str) -> list[Path]:
    configured = Path(configured_path)
    repo_root = Path(__file__).resolve().parents[4]

    # 按优先级候选：显式路径 -> 当前工作目录 -> 仓库根目录 -> 默认 key 文件。
    candidates = [
        configured,
        Path.cwd() / configured,
        repo_root / configured,
        repo_root / "doc" / "key.txt",
    ]

    unique: list[Path] = []
    for item in candidates:
        resolved = item.resolve() if not item.is_absolute() else item
        if resolved not in unique:
            unique.append(resolved)
    return unique


def _read_key_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        match = _KEY_LINE.match(stripped)
        if not match:
            continue

        key = match.group(1).strip()
        value = match.group(3).strip().strip('"')
        data[key] = value
    return data


def _hydrate_from_key_file(settings: Settings) -> Settings:
    # 如果环境变量已完整提供密钥信息，不再覆盖。
    if settings.openai_api_key and settings.openai_base_url and settings.model_provider:
        return settings

    key_data: dict[str, str] = {}
    for candidate in _candidate_key_paths(settings.key_file_path):
        if candidate.exists():
            key_data = _read_key_file(candidate)
            break

    if not key_data:
        return settings

    if not settings.model_provider:
        settings.model_provider = key_data.get("name", settings.model_provider)
    if not settings.openai_base_url:
        settings.openai_base_url = key_data.get("base_url", settings.openai_base_url)
    if not settings.openai_model or settings.openai_model == DEFAULT_OPENAI_MODEL:
        settings.openai_model = key_data.get("model", settings.openai_model)
    if (
        not settings.openai_reasoning_effort
        or settings.openai_reasoning_effort == DEFAULT_OPENAI_REASONING_EFFORT
    ):
        settings.openai_reasoning_effort = key_data.get(
            "model_reasoning_effort", settings.openai_reasoning_effort
        )
    if not settings.openai_api_key:
        settings.openai_api_key = key_data.get("OPENAI_API_KEY", settings.openai_api_key)
    if not settings.model_routes:
        settings.model_routes = key_data.get("MODEL_ROUTES", key_data.get("model_routes", settings.model_routes))
    if not settings.model_routes_path:
        settings.model_routes_path = key_data.get(
            "MODEL_ROUTES_PATH",
            key_data.get("model_routes_path", settings.model_routes_path),
        )

    return settings


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    settings = Settings()
    return _hydrate_from_key_file(settings)


