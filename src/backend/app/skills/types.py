from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SkillParameter:
    name: str
    description: str
    required: bool = False
    param_type: str = "string"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "required": self.required,
            "param_type": self.param_type,
        }


@dataclass(slots=True)
class SkillSpec:
    skill_id: str
    name: str
    description: str
    triggers: list[str]
    parameters: list[SkillParameter]
    examples: list[str]
    path: Path
    raw_markdown: str
    mtime_ns: int
    plugin_id: str | None = None
    plugin_name: str | None = None
    plugin_enabled: bool = True
    plugin_config_schema: dict[str, Any] = field(default_factory=dict)
    plugin_config: dict[str, Any] = field(default_factory=dict)
    default_tools: list[str] = field(default_factory=list)
    optional_tools: list[str] = field(default_factory=list)
    entry_script: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "triggers": list(self.triggers),
            "parameters": [item.to_dict() for item in self.parameters],
            "examples": list(self.examples),
            "path": str(self.path),
            "mtime_ns": self.mtime_ns,
            "raw_markdown": self.raw_markdown,
            "plugin_id": self.plugin_id,
            "plugin_name": self.plugin_name,
            "plugin_enabled": self.plugin_enabled,
            "plugin_config_schema": self.plugin_config_schema,
            "plugin_config": self.plugin_config,
            "default_tools": list(self.default_tools),
            "optional_tools": list(self.optional_tools),
            "entry_script": self.entry_script,
        }

    def prompt_view(self) -> str:
        trigger_text = ", ".join(self.triggers) if self.triggers else "(none)"
        if self.parameters:
            params = "; ".join(
                f"{item.name}({item.param_type},{'required' if item.required else 'optional'}): {item.description}"
                for item in self.parameters
            )
        else:
            params = "(none)"

        example = self.examples[0] if self.examples else "(none)"
        default_tools = ", ".join(self.default_tools) if self.default_tools else "(none)"
        optional_tools = ", ".join(self.optional_tools) if self.optional_tools else "(none)"
        plugin_text = self.plugin_name or self.plugin_id or "standalone"
        return (
            f"{self.name} [id={self.skill_id}]\n"
            f"  - desc: {self.description}\n"
            f"  - plugin: {plugin_text}\n"
            f"  - triggers: {trigger_text}\n"
            f"  - params: {params}\n"
            f"  - default_tools: {default_tools}\n"
            f"  - optional_tools: {optional_tools}\n"
            f"  - example: {example}"
        )
