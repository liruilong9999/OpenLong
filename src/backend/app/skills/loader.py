from __future__ import annotations

from pathlib import Path

from app.skills.parser import Skill, SkillParser
from app.workspace.manager import WorkspaceManager


class SkillLoader:
    def __init__(self, workspace_manager: WorkspaceManager) -> None:
        self._workspace_manager = workspace_manager
        self._parser = SkillParser()

    def load(self, agent_id: str) -> list[Skill]:
        workspace = self._workspace_manager.ensure_agent_workspace(agent_id)
        skills_dir = workspace / "skills"
        if not skills_dir.exists():
            return []

        skills: list[Skill] = []
        for path in skills_dir.iterdir():
            if path.is_dir():
                skills.append(self._parser.parse(path))
        return skills

    def list_skill_names(self, agent_id: str) -> list[str]:
        return [skill.name for skill in self.load(agent_id)]
