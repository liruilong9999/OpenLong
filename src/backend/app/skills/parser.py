from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Skill:
    name: str
    description: str
    path: Path


class SkillParser:
    def parse(self, skill_path: Path) -> Skill:
        skill_md = skill_path / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8") if skill_md.exists() else ""
        first_line = text.splitlines()[0].strip("# ") if text else skill_path.name
        description = text[:300].strip() if text else "No skill description yet."
        return Skill(name=first_line or skill_path.name, description=description, path=skill_path)
