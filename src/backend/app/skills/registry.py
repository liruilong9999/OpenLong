from __future__ import annotations

import re
from typing import Any

from app.skills.types import SkillSpec


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]+")


class SkillRegistry:
    def __init__(self) -> None:
        self._skills_by_agent: dict[str, dict[str, SkillSpec]] = {}

    def register(self, agent_id: str, skills: list[SkillSpec]) -> None:
        mapping = {item.skill_id: item for item in skills}
        self._skills_by_agent[agent_id] = mapping

    def list(self, agent_id: str) -> list[SkillSpec]:
        items = list(self._skills_by_agent.get(agent_id, {}).values())
        items.sort(key=lambda item: item.skill_id)
        return items

    def get(self, agent_id: str, skill_id: str) -> SkillSpec | None:
        return self._skills_by_agent.get(agent_id, {}).get(skill_id)

    def match(self, agent_id: str, text: str, max_items: int = 5) -> list[tuple[SkillSpec, float]]:
        skills = self.list(agent_id)
        if not skills:
            return []

        query = text.strip().lower()
        query_tokens = self._tokens(query)

        scored: list[tuple[SkillSpec, float]] = []
        for skill in skills:
            score = self._score(skill=skill, query=query, query_tokens=query_tokens)
            if score <= 0.0 and query:
                continue
            scored.append((skill, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[: max(max_items, 0)]

    def snapshot(self, agent_id: str) -> dict[str, Any]:
        skills = self.list(agent_id)
        return {
            "agent_id": agent_id,
            "count": len(skills),
            "skills": [item.to_dict() for item in skills],
        }

    def _score(self, *, skill: SkillSpec, query: str, query_tokens: set[str]) -> float:
        if not query:
            return 0.1

        score = 0.0
        skill_name = skill.name.lower()
        skill_id = skill.skill_id.lower()
        description = skill.description.lower()

        if skill_name in query or skill_id in query:
            score += 0.55

        for trigger in skill.triggers:
            normalized = trigger.lower().strip()
            if not normalized:
                continue
            if normalized in query:
                score += 0.33
                continue

            trigger_tokens = self._tokens(normalized)
            if trigger_tokens:
                overlap = len(query_tokens.intersection(trigger_tokens))
                score += (overlap / len(trigger_tokens)) * 0.25

        desc_tokens = self._tokens(description)
        if desc_tokens:
            overlap = len(query_tokens.intersection(desc_tokens))
            score += (overlap / len(desc_tokens)) * 0.12

        for param in skill.parameters:
            param_name = param.name.lower()
            if param_name and param_name in query:
                score += 0.06

        return round(score, 6)

    def _tokens(self, text: str) -> set[str]:
        return {token.lower() for token in _TOKEN_PATTERN.findall(text or "")}
