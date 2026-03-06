from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


CONTEXT_FILES = ["USER.md", "SOUL.md", "IDENTITY.md", "RULES.md", "STYLE.md"]


@dataclass(slots=True)
class ContextManager:
    workspace_path: Path

    def build_context(self) -> str:
        blocks: list[str] = []
        for filename in CONTEXT_FILES:
            path = self.workspace_path / filename
            if path.exists():
                content = path.read_text(encoding="utf-8").strip()
            else:
                content = ""
            blocks.append(f"## {filename}\n{content or '(empty)'}")

        return "\n\n".join(blocks)
