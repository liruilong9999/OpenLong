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
        return (
            f"{self.name} [id={self.skill_id}]\n"
            f"  - desc: {self.description}\n"
            f"  - triggers: {trigger_text}\n"
            f"  - params: {params}\n"
            f"  - example: {example}"
        )
