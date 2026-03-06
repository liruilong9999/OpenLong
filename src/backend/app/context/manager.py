from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


CONTEXT_FILES = ["USER.md", "SOUL.md", "IDENTITY.md", "RULES.md", "STYLE.md"]
CONTEXT_PRIORITY = ["RULES.md", "IDENTITY.md", "SOUL.md", "STYLE.md", "USER.md"]
DYNAMIC_EDITABLE_CONTEXTS = {"USER.md", "STYLE.md"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True, frozen=True)
class ContextSection:
    filename: str
    title: str
    body: str
    raw: str
    line_count: int
    char_count: int
    mtime_ns: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "title": self.title,
            "body": self.body,
            "raw": self.raw,
            "line_count": self.line_count,
            "char_count": self.char_count,
            "mtime_ns": self.mtime_ns,
        }


@dataclass(slots=True)
class ContextSnapshot:
    workspace_path: Path
    priority_order: list[str]
    editable_files: list[str]
    sections: dict[str, ContextSection]
    prompt_block: str
    loaded_at: datetime = field(default_factory=_utc_now)
    cache_hit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_path": str(self.workspace_path),
            "priority_order": self.priority_order,
            "editable_files": self.editable_files,
            "cache_hit": self.cache_hit,
            "loaded_at": self.loaded_at.isoformat(),
            "files": {name: section.to_dict() for name, section in self.sections.items()},
            "prompt_block": self.prompt_block,
        }

    def clone_with_cache_flag(self, cache_hit: bool) -> "ContextSnapshot":
        return ContextSnapshot(
            workspace_path=self.workspace_path,
            priority_order=list(self.priority_order),
            editable_files=list(self.editable_files),
            sections=dict(self.sections),
            prompt_block=self.prompt_block,
            loaded_at=self.loaded_at,
            cache_hit=cache_hit,
        )


@dataclass(slots=True)
class _CacheEntry:
    mtimes: dict[str, int]
    snapshot: ContextSnapshot


class ContextManager:
    def __init__(
        self,
        *,
        context_files: list[str] | None = None,
        priority_order: list[str] | None = None,
        editable_files: set[str] | None = None,
    ) -> None:
        self._context_files = context_files or list(CONTEXT_FILES)
        self._priority_order = priority_order or list(CONTEXT_PRIORITY)
        self._editable_files = editable_files or set(DYNAMIC_EDITABLE_CONTEXTS)

        self._cache: dict[str, _CacheEntry] = {}
        self._cache_hits = 0
        self._cache_misses = 0
        self._lock = Lock()

    def load(self, workspace_path: Path, force_refresh: bool = False) -> ContextSnapshot:
        workspace = workspace_path.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        cache_key = str(workspace)
        mtimes = self._collect_mtimes(workspace)

        with self._lock:
            cached = self._cache.get(cache_key)
            if not force_refresh and cached is not None and cached.mtimes == mtimes:
                self._cache_hits += 1
                return cached.snapshot.clone_with_cache_flag(cache_hit=True)

        sections: dict[str, ContextSection] = {}
        for filename in self._context_files:
            path = workspace / filename
            raw = path.read_text(encoding="utf-8") if path.exists() else ""
            title, body = self._parse_markdown(filename=filename, raw_text=raw)

            sections[filename] = ContextSection(
                filename=filename,
                title=title,
                body=body,
                raw=raw.strip(),
                line_count=len(raw.splitlines()),
                char_count=len(raw),
                mtime_ns=mtimes[filename],
            )

        prompt_block = self._compose_prompt_block(sections)
        snapshot = ContextSnapshot(
            workspace_path=workspace,
            priority_order=list(self._priority_order),
            editable_files=sorted(self._editable_files),
            sections=sections,
            prompt_block=prompt_block,
            cache_hit=False,
        )

        with self._lock:
            self._cache_misses += 1
            self._cache[cache_key] = _CacheEntry(mtimes=mtimes, snapshot=snapshot)

        return snapshot

    def build_context(self, workspace_path: Path, force_refresh: bool = False) -> str:
        return self.load(workspace_path, force_refresh=force_refresh).prompt_block

    def update_context(
        self,
        workspace_path: Path,
        context_name: str,
        content: str,
        dynamic_only: bool = True,
    ) -> ContextSnapshot:
        filename = self._normalize_context_name(context_name)
        if dynamic_only and filename not in self._editable_files:
            raise PermissionError(f"{filename} is read-only, only USER.md and STYLE.md can be updated")

        workspace = workspace_path.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        target = workspace / filename

        normalized = content.rstrip()
        target.write_text((normalized + "\n") if normalized else "", encoding="utf-8")

        self.invalidate(workspace)
        return self.load(workspace, force_refresh=True)

    def invalidate(self, workspace_path: Path) -> None:
        cache_key = str(workspace_path.resolve())
        with self._lock:
            self._cache.pop(cache_key, None)

    def cache_stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "entries": len(self._cache),
                "hits": self._cache_hits,
                "misses": self._cache_misses,
            }

    def _collect_mtimes(self, workspace: Path) -> dict[str, int]:
        mtimes: dict[str, int] = {}
        for filename in self._context_files:
            path = workspace / filename
            mtimes[filename] = path.stat().st_mtime_ns if path.exists() else -1
        return mtimes

    def _normalize_context_name(self, context_name: str) -> str:
        text = context_name.strip()
        if not text:
            raise ValueError("context name cannot be empty")

        if not text.lower().endswith(".md"):
            text = f"{text}.md"

        for filename in self._context_files:
            if filename.lower() == text.lower():
                return filename

        raise ValueError(f"unsupported context file: {context_name}")

    def _parse_markdown(self, filename: str, raw_text: str) -> tuple[str, str]:
        stripped = raw_text.replace("\ufeff", "").strip()
        default_title = filename.replace(".md", "")
        if not stripped:
            return default_title, ""

        lines = stripped.splitlines()
        first = lines[0].strip()
        if first.startswith("#"):
            title = first.lstrip("# ").strip() or default_title
            body = "\n".join(lines[1:]).strip()
            return title, body

        return default_title, stripped

    def _compose_prompt_block(self, sections: dict[str, ContextSection]) -> str:
        blocks: list[str] = []
        for filename in self._priority_order:
            section = sections.get(filename)
            if section is None:
                blocks.append(f"## {filename}\n(empty)")
                continue

            content = section.body or section.raw or "(empty)"
            blocks.append(f"## {filename}\n{content}")

        return "\n\n".join(blocks)
