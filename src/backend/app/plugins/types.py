from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PluginManifest:
    plugin_id: str
    name: str
    description: str
    version: str
    enabled: bool
    config_schema: dict[str, Any]
    config: dict[str, Any]
    skills: list[str]
    default_tools: list[str] = field(default_factory=list)
    optional_tools: list[str] = field(default_factory=list)
    entry_script: str | None = None
    path: Path = field(default_factory=Path)
    manifest_path: Path = field(default_factory=Path)
    raw_manifest: dict[str, Any] = field(default_factory=dict)
    mtime_ns: int = -1

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "enabled": self.enabled,
            "config_schema": self.config_schema,
            "config": self.config,
            "skills": list(self.skills),
            "default_tools": list(self.default_tools),
            "optional_tools": list(self.optional_tools),
            "entry_script": self.entry_script,
            "path": str(self.path),
            "manifest_path": str(self.manifest_path),
            "mtime_ns": self.mtime_ns,
        }
