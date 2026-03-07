from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any

from app.plugins.manager import PluginManager
from app.skills.parser import SkillParser
from app.skills.registry import SkillRegistry
from app.skills.types import SkillSpec
from app.workspace.manager import WorkspaceManager


SKILL_MD_TEMPLATE = """# {skill_name}

## 技能说明
用一句话说明该技能负责什么。

## 触发条件
- 触发关键词1
- 触发关键词2

## 参数说明
- input(string,required): 输入内容
- option(string,optional): 可选参数

## 示例
- 用户说：请用该技能处理这段文本
- Agent 行为：匹配该技能并按参数调用工具
"""


PLUGIN_MANIFEST_TEMPLATE = {
    "id": "new_plugin",
    "name": "New Plugin",
    "description": "Describe what this plugin contributes.",
    "version": "0.1.0",
    "enabled": True,
    "config_schema": {"type": "object", "properties": {}, "required": []},
    "config": {},
    "skills": ["skills"],
    "default_tools": [],
    "optional_tools": [],
}


class SkillLoader:
    def __init__(self, workspace_manager: WorkspaceManager, plugin_manager: PluginManager | None = None) -> None:
        self._workspace_manager = workspace_manager
        self._plugin_manager = plugin_manager or PluginManager(workspace_manager)
        self._parser = SkillParser()
        self._registry = SkillRegistry()

        self._signatures: dict[str, tuple[tuple[str, int, int], ...]] = {}
        self._hits = 0
        self._misses = 0
        self._lock = Lock()

    def load(self, agent_id: str, force_refresh: bool = False) -> list[SkillSpec]:
        workspace = self._workspace_manager.ensure_agent_workspace(agent_id)
        skills_dir = workspace / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        plugins = self._plugin_manager.load(agent_id, force_refresh=force_refresh)

        signature = self._directory_signature(skills_dir, plugins)
        with self._lock:
            cached_signature = self._signatures.get(agent_id)
            if not force_refresh and cached_signature == signature:
                self._hits += 1
                return self._registry.list(agent_id)

        skills = self._load_workspace_skills(skills_dir)
        skills.extend(self._load_plugin_skills(plugins))

        self._registry.register(agent_id, skills)
        with self._lock:
            self._misses += 1
            self._signatures[agent_id] = signature

        return skills

    def list_skill_names(self, agent_id: str, force_refresh: bool = False) -> list[str]:
        return [skill.name for skill in self.load(agent_id, force_refresh=force_refresh)]

    def match(self, agent_id: str, user_message: str, max_items: int = 5) -> list[SkillSpec]:
        self.load(agent_id)
        matches = self._registry.match(agent_id=agent_id, text=user_message, max_items=max_items)
        return [skill for skill, _ in matches]

    def match_with_scores(self, agent_id: str, user_message: str, max_items: int = 5) -> list[dict[str, Any]]:
        self.load(agent_id)
        matches = self._registry.match(agent_id=agent_id, text=user_message, max_items=max_items)
        return [{"score": score, "skill": skill.to_dict()} for skill, score in matches]

    def reload(self, agent_id: str) -> list[SkillSpec]:
        return self.load(agent_id, force_refresh=True)

    def upsert_skill_markdown(self, agent_id: str, skill_id: str, markdown: str) -> SkillSpec:
        normalized = self._normalize_skill_id(skill_id)
        workspace = self._workspace_manager.ensure_agent_workspace(agent_id)
        skill_dir = workspace / "skills" / normalized
        skill_dir.mkdir(parents=True, exist_ok=True)

        content = markdown.strip()
        if not content:
            content = self.render_template(normalized)

        (skill_dir / "SKILL.md").write_text(content + "\n", encoding="utf-8")

        skills = self.load(agent_id, force_refresh=True)
        for skill in skills:
            if skill.skill_id == normalized and skill.plugin_id is None:
                return skill

        return self._parser.parse(skill_dir)

    def delete_skill(self, agent_id: str, skill_id: str) -> bool:
        normalized = self._normalize_skill_id(skill_id)
        workspace = self._workspace_manager.ensure_agent_workspace(agent_id)
        skill_dir = workspace / "skills" / normalized
        if not skill_dir.exists():
            return False

        for file in skill_dir.rglob("*"):
            if file.is_file():
                file.unlink()
        for directory in sorted(skill_dir.rglob("*"), reverse=True):
            if directory.is_dir():
                directory.rmdir()
        skill_dir.rmdir()

        self.load(agent_id, force_refresh=True)
        return True

    def snapshot(self, agent_id: str, force_refresh: bool = False) -> dict[str, Any]:
        skills = self.load(agent_id, force_refresh=force_refresh)
        return {
            "agent_id": agent_id,
            "count": len(skills),
            "skills": [skill.to_dict() for skill in skills],
            "plugins": self._plugin_manager.snapshot(agent_id, force_refresh=force_refresh),
        }

    def cache_stats(self) -> dict[str, int]:
        plugin_stats = self._plugin_manager.cache_stats()
        with self._lock:
            return {
                "entries": len(self._signatures),
                "hits": self._hits,
                "misses": self._misses,
                "plugin_entries": plugin_stats["entries"],
                "plugin_hits": plugin_stats["hits"],
                "plugin_misses": plugin_stats["misses"],
            }

    def render_template(self, skill_name: str) -> str:
        return SKILL_MD_TEMPLATE.format(skill_name=skill_name)

    def plugin_template(self, plugin_id: str) -> dict[str, Any]:
        template = dict(PLUGIN_MANIFEST_TEMPLATE)
        template["id"] = plugin_id
        template["name"] = plugin_id.replace("_", " ").title()
        return template

    def list_plugins(self, agent_id: str, force_refresh: bool = False) -> dict[str, Any]:
        return self._plugin_manager.snapshot(agent_id, force_refresh=force_refresh)

    def reload_plugins(self, agent_id: str) -> dict[str, Any]:
        self._plugin_manager.load(agent_id, force_refresh=True)
        self.load(agent_id, force_refresh=True)
        return self.list_plugins(agent_id)

    def install_plugin(
        self,
        agent_id: str,
        plugin_id: str,
        manifest: dict[str, Any],
        skills: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        plugin = self._plugin_manager.install(agent_id=agent_id, plugin_id=plugin_id, manifest=manifest, skills=skills)
        self.load(agent_id, force_refresh=True)
        return plugin.to_dict()

    def set_plugin_enabled(self, agent_id: str, plugin_id: str, enabled: bool) -> dict[str, Any]:
        plugin = self._plugin_manager.set_enabled(agent_id=agent_id, plugin_id=plugin_id, enabled=enabled)
        self.load(agent_id, force_refresh=True)
        return plugin.to_dict()

    def delete_plugin(self, agent_id: str, plugin_id: str) -> bool:
        deleted = self._plugin_manager.delete(agent_id=agent_id, plugin_id=plugin_id)
        if deleted:
            self.load(agent_id, force_refresh=True)
        return deleted

    def _load_workspace_skills(self, skills_dir: Path) -> list[SkillSpec]:
        skills: list[SkillSpec] = []
        for path in sorted(skills_dir.iterdir(), key=lambda item: item.name):
            if not path.is_dir():
                continue
            if not (path / "SKILL.md").exists():
                continue
            skills.append(self._parser.parse(path))
        return skills

    def _load_plugin_skills(self, plugins: list[Any]) -> list[SkillSpec]:
        skills: list[SkillSpec] = []
        for plugin in plugins:
            if not plugin.enabled:
                continue
            for relative in plugin.skills:
                candidate = (plugin.path / relative).resolve()
                if not candidate.exists() or not candidate.is_dir():
                    continue
                if (candidate / "SKILL.md").exists():
                    skills.append(self._parser.parse(candidate, plugin=plugin))
                    continue
                for path in sorted(candidate.iterdir(), key=lambda item: item.name):
                    if not path.is_dir() or not (path / "SKILL.md").exists():
                        continue
                    skills.append(self._parser.parse(path, plugin=plugin))
        return skills

    def _directory_signature(self, skills_dir: Path, plugins: list[Any]) -> tuple[tuple[str, int, int], ...]:
        records: list[tuple[str, int, int]] = []
        for skill_md in sorted(skills_dir.glob("*/SKILL.md"), key=lambda item: str(item)):
            stat = skill_md.stat()
            relative = skill_md.relative_to(skills_dir)
            records.append((f"skills/{relative.as_posix()}", stat.st_mtime_ns, stat.st_size))
        for plugin in plugins:
            records.append((f"plugin/{plugin.plugin_id}/{plugin.mtime_ns}", plugin.mtime_ns, len(plugin.skills)))
        return tuple(records)

    def _normalize_skill_id(self, skill_id: str) -> str:
        normalized = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in skill_id.strip())
        normalized = normalized.strip("_")
        if not normalized:
            raise ValueError("skill_id cannot be empty")
        return normalized
