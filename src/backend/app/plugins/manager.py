from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

from app.plugins.types import PluginManifest
from app.workspace.manager import WorkspaceManager


PLUGIN_MANIFEST_FILE = "openlong.plugin.json"


class PluginManager:
    def __init__(self, workspace_manager: WorkspaceManager) -> None:
        self._workspace_manager = workspace_manager
        self._signatures: dict[str, tuple[tuple[str, int, int], ...]] = {}
        self._plugins: dict[str, dict[str, PluginManifest]] = {}
        self._hits = 0
        self._misses = 0
        self._lock = Lock()

    def load(self, agent_id: str, force_refresh: bool = False) -> list[PluginManifest]:
        plugins_dir = self._plugins_dir(agent_id)
        signature = self._directory_signature(plugins_dir)

        with self._lock:
            cached_signature = self._signatures.get(agent_id)
            if not force_refresh and cached_signature == signature:
                self._hits += 1
                items = list(self._plugins.get(agent_id, {}).values())
                items.sort(key=lambda item: item.plugin_id)
                return items

        plugins: list[PluginManifest] = []
        for path in sorted(plugins_dir.iterdir(), key=lambda item: item.name):
            if not path.is_dir():
                continue
            manifest_path = path / PLUGIN_MANIFEST_FILE
            if not manifest_path.exists():
                continue
            plugins.append(self._parse_manifest(path, manifest_path))

        with self._lock:
            self._misses += 1
            self._signatures[agent_id] = signature
            self._plugins[agent_id] = {item.plugin_id: item for item in plugins}

        return plugins

    def list(self, agent_id: str, force_refresh: bool = False) -> list[PluginManifest]:
        if force_refresh:
            return self.load(agent_id, force_refresh=True)
        with self._lock:
            items = list(self._plugins.get(agent_id, {}).values())
        items.sort(key=lambda item: item.plugin_id)
        return items

    def get(self, agent_id: str, plugin_id: str) -> PluginManifest | None:
        self.load(agent_id)
        with self._lock:
            return self._plugins.get(agent_id, {}).get(plugin_id)

    def snapshot(self, agent_id: str, force_refresh: bool = False) -> dict[str, Any]:
        plugins = self.load(agent_id, force_refresh=force_refresh)
        return {
            "agent_id": agent_id,
            "count": len(plugins),
            "plugins": [item.to_dict() for item in plugins],
            "cache": self.cache_stats(),
        }

    def install(
        self,
        agent_id: str,
        plugin_id: str,
        manifest: dict[str, Any],
        skills: dict[str, str] | None = None,
    ) -> PluginManifest:
        normalized = self._normalize_plugin_id(plugin_id)
        plugins_dir = self._plugins_dir(agent_id)
        plugin_dir = plugins_dir / normalized
        plugin_dir.mkdir(parents=True, exist_ok=True)

        payload = dict(manifest or {})
        payload["id"] = payload.get("id") or normalized
        payload["name"] = payload.get("name") or normalized
        payload["description"] = payload.get("description") or "No plugin description provided."
        payload["version"] = payload.get("version") or "0.1.0"
        payload["enabled"] = bool(payload.get("enabled", True))
        payload["config_schema"] = payload.get("config_schema") or {"type": "object", "properties": {}, "required": []}
        payload["config"] = payload.get("config") or {}
        payload["skills"] = payload.get("skills") or ["skills"]
        payload["default_tools"] = payload.get("default_tools") or []
        payload["optional_tools"] = payload.get("optional_tools") or []
        payload["entry_script"] = payload.get("entry_script")

        self._validate_manifest(plugin_dir, payload)

        if skills:
            for skill_id, markdown in skills.items():
                skill_dir = plugin_dir / "skills" / self._normalize_plugin_id(skill_id)
                skill_dir.mkdir(parents=True, exist_ok=True)
                (skill_dir / "SKILL.md").write_text(str(markdown).rstrip() + "\n", encoding="utf-8")

        (plugin_dir / PLUGIN_MANIFEST_FILE).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return next(item for item in self.load(agent_id, force_refresh=True) if item.plugin_id == normalized)

    def set_enabled(self, agent_id: str, plugin_id: str, enabled: bool) -> PluginManifest:
        plugin = self.get(agent_id, plugin_id)
        if plugin is None:
            raise FileNotFoundError(plugin_id)
        payload = dict(plugin.raw_manifest)
        payload["enabled"] = bool(enabled)
        self._validate_manifest(plugin.path, payload)
        plugin.manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return next(item for item in self.load(agent_id, force_refresh=True) if item.plugin_id == plugin_id)

    def delete(self, agent_id: str, plugin_id: str) -> bool:
        normalized = self._normalize_plugin_id(plugin_id)
        plugin_dir = self._plugins_dir(agent_id) / normalized
        if not plugin_dir.exists():
            return False
        for item in sorted(plugin_dir.rglob("*"), reverse=True):
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                item.rmdir()
        plugin_dir.rmdir()
        self.load(agent_id, force_refresh=True)
        return True

    def cache_stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "entries": len(self._signatures),
                "hits": self._hits,
                "misses": self._misses,
            }

    def _plugins_dir(self, agent_id: str) -> Path:
        workspace = self._workspace_manager.ensure_agent_workspace(agent_id)
        path = workspace / "plugins"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _directory_signature(self, plugins_dir: Path) -> tuple[tuple[str, int, int], ...]:
        records: list[tuple[str, int, int]] = []
        for manifest_path in sorted(plugins_dir.glob(f"*/{PLUGIN_MANIFEST_FILE}"), key=lambda item: str(item)):
            stat = manifest_path.stat()
            records.append((manifest_path.relative_to(plugins_dir).as_posix(), stat.st_mtime_ns, stat.st_size))
        return tuple(records)

    def _parse_manifest(self, plugin_dir: Path, manifest_path: Path) -> PluginManifest:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        self._validate_manifest(plugin_dir, payload)
        stat = manifest_path.stat()
        return PluginManifest(
            plugin_id=str(payload["id"]),
            name=str(payload["name"]),
            description=str(payload["description"]),
            version=str(payload["version"]),
            enabled=bool(payload.get("enabled", True)),
            config_schema=dict(payload.get("config_schema") or {}),
            config=dict(payload.get("config") or {}),
            skills=[str(item) for item in list(payload.get("skills") or [])],
            default_tools=[str(item) for item in list(payload.get("default_tools") or [])],
            optional_tools=[str(item) for item in list(payload.get("optional_tools") or [])],
            entry_script=str(payload.get("entry_script")) if payload.get("entry_script") else None,
            path=plugin_dir,
            manifest_path=manifest_path,
            raw_manifest=payload,
            mtime_ns=stat.st_mtime_ns,
        )

    def _validate_manifest(self, plugin_dir: Path, payload: dict[str, Any]) -> None:
        plugin_id = self._normalize_plugin_id(str(payload.get("id") or ""))
        if not plugin_id:
            raise ValueError("plugin manifest requires id")
        if plugin_id != plugin_dir.name:
            raise ValueError("plugin manifest id must match plugin directory name")

        if not str(payload.get("name") or "").strip():
            raise ValueError("plugin manifest requires name")
        if not isinstance(payload.get("config_schema") or {}, dict):
            raise ValueError("plugin config_schema must be an object")
        if not isinstance(payload.get("config") or {}, dict):
            raise ValueError("plugin config must be an object")

        required_fields = list((payload.get("config_schema") or {}).get("required") or [])
        config = payload.get("config") or {}
        for field_name in required_fields:
            if field_name not in config:
                raise ValueError(f"plugin config missing required field: {field_name}")

        properties = (payload.get("config_schema") or {}).get("properties") or {}
        if isinstance(properties, dict):
            for field_name, schema in properties.items():
                if field_name not in config:
                    continue
                self._validate_config_value(field_name, config[field_name], schema if isinstance(schema, dict) else {})

        skills = payload.get("skills") or []
        if not isinstance(skills, list) or not all(isinstance(item, str) and item.strip() for item in skills):
            raise ValueError("plugin skills must be a non-empty list of strings")

        for field_name in ["default_tools", "optional_tools"]:
            value = payload.get(field_name) or []
            if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
                raise ValueError(f"plugin {field_name} must be a list of strings")

        entry_script = payload.get("entry_script")
        if entry_script:
            script_path = plugin_dir / str(entry_script)
            if not script_path.exists() or not script_path.is_file():
                raise ValueError(f"plugin entry_script not found: {entry_script}")

    def _validate_config_value(self, field_name: str, value: Any, schema: dict[str, Any]) -> None:
        schema_type = str(schema.get("type") or "").strip().lower()
        if schema_type == "string" and not isinstance(value, str):
            raise ValueError(f"plugin config field {field_name} must be a string")
        if schema_type == "boolean" and not isinstance(value, bool):
            raise ValueError(f"plugin config field {field_name} must be a boolean")
        if schema_type == "number" and not isinstance(value, (int, float)):
            raise ValueError(f"plugin config field {field_name} must be a number")
        if schema_type == "object" and not isinstance(value, dict):
            raise ValueError(f"plugin config field {field_name} must be an object")
        if schema_type == "array" and not isinstance(value, list):
            raise ValueError(f"plugin config field {field_name} must be an array")
        enum_values = schema.get("enum")
        if isinstance(enum_values, list) and value not in enum_values:
            raise ValueError(f"plugin config field {field_name} must be one of: {', '.join(str(item) for item in enum_values)}")

    def _normalize_plugin_id(self, plugin_id: str) -> str:
        normalized = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in plugin_id.strip())
        return normalized.strip("_")
