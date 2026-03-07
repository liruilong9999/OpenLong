from __future__ import annotations

from pathlib import Path
import re

from app.plugins.types import PluginManifest
from app.skills.types import SkillParameter, SkillSpec


_SECTION_ALIASES = {
    "技能说明": "description",
    "description": "description",
    "skill description": "description",
    "触发条件": "triggers",
    "triggers": "triggers",
    "trigger": "triggers",
    "参数说明": "parameters",
    "parameters": "parameters",
    "params": "parameters",
    "示例": "examples",
    "examples": "examples",
    "example": "examples",
}

_PARAM_PATTERN = re.compile(
    r"^\s*[-*]\s*([A-Za-z0-9_\-]+)\s*(?:\(([^)]*)\))?\s*[:：]?\s*(.*)$"
)


class SkillParser:
    def parse(self, skill_path: Path, plugin: PluginManifest | None = None) -> SkillSpec:
        skill_md = skill_path / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8") if skill_md.exists() else ""
        mtime_ns = skill_md.stat().st_mtime_ns if skill_md.exists() else -1

        title, sections = self._split_sections(text)

        skill_id = skill_path.name
        name = title or skill_id

        description = sections.get("description", "").strip()
        if not description:
            description = "No skill description provided."

        triggers = self._parse_bullets(sections.get("triggers", ""))
        parameters = self._parse_parameters(sections.get("parameters", ""))
        examples = self._parse_examples(sections.get("examples", ""))

        return SkillSpec(
            skill_id=skill_id,
            name=name,
            description=description,
            triggers=triggers,
            parameters=parameters,
            examples=examples,
            path=skill_path,
            raw_markdown=text,
            mtime_ns=mtime_ns,
            plugin_id=plugin.plugin_id if plugin else None,
            plugin_name=plugin.name if plugin else None,
            plugin_enabled=plugin.enabled if plugin else True,
            plugin_config_schema=dict(plugin.config_schema) if plugin else {},
            plugin_config=dict(plugin.config) if plugin else {},
            default_tools=list(plugin.default_tools) if plugin else [],
            optional_tools=list(plugin.optional_tools) if plugin else [],
            entry_script=plugin.entry_script if plugin else None,
        )

    def _split_sections(self, markdown: str) -> tuple[str, dict[str, str]]:
        title = ""
        sections: dict[str, list[str]] = {
            "description": [],
            "triggers": [],
            "parameters": [],
            "examples": [],
        }

        current_key = "description"
        section_order = ["description", "triggers", "parameters", "examples"]
        order_index = 0
        for raw_line in markdown.splitlines():
            line = raw_line.rstrip("\n")
            stripped = line.strip()

            if stripped.startswith("# ") and not title:
                title = stripped[2:].strip()
                continue

            if stripped.startswith("## "):
                section_title = stripped[3:].strip().lower()
                normalized = self._normalize_section_key(section_title)
                if normalized is None:
                    if order_index < len(section_order):
                        normalized = section_order[order_index]
                        order_index += 1
                else:
                    if normalized in section_order:
                        order_index = max(order_index, section_order.index(normalized) + 1)

                current_key = normalized or current_key
                continue

            sections[current_key].append(line)

        return title, {key: "\n".join(value).strip() for key, value in sections.items()}

    def _normalize_section_key(self, section_title: str) -> str | None:
        if section_title in _SECTION_ALIASES:
            return _SECTION_ALIASES[section_title]

        if any(token in section_title for token in ["trigger", "触发"]):
            return "triggers"
        if any(token in section_title for token in ["param", "参数"]):
            return "parameters"
        if any(token in section_title for token in ["example", "示例"]):
            return "examples"
        if any(token in section_title for token in ["description", "说明"]):
            return "description"

        return None

    def _parse_bullets(self, text: str) -> list[str]:
        items: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith("- ") or stripped.startswith("* "):
                items.append(stripped[2:].strip())
            else:
                items.append(stripped)

        deduped: list[str] = []
        for item in items:
            if item and item not in deduped:
                deduped.append(item)
        return deduped

    def _parse_parameters(self, text: str) -> list[SkillParameter]:
        params: list[SkillParameter] = []

        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue

            match = _PARAM_PATTERN.match(stripped)
            if not match:
                continue

            name = match.group(1).strip()
            attrs = (match.group(2) or "").lower()
            desc = (match.group(3) or "").strip() or "No description"

            required = "required" in attrs or "必填" in attrs
            param_type = "string"
            for candidate in ["string", "number", "bool", "boolean", "object", "array", "path", "url"]:
                if candidate in attrs:
                    param_type = candidate
                    break

            params.append(
                SkillParameter(
                    name=name,
                    description=desc,
                    required=required,
                    param_type=param_type,
                )
            )

        return params

    def _parse_examples(self, text: str) -> list[str]:
        examples: list[str] = []
        current: list[str] = []

        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                if current:
                    examples.append(" ".join(current).strip())
                    current = []
                continue

            if stripped.startswith("- ") or stripped.startswith("* "):
                if current:
                    examples.append(" ".join(current).strip())
                    current = []
                examples.append(stripped[2:].strip())
            else:
                current.append(stripped)

        if current:
            examples.append(" ".join(current).strip())

        deduped: list[str] = []
        for item in examples:
            if item and item not in deduped:
                deduped.append(item)
        return deduped
