from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import mimetypes
from pathlib import Path
import re
import shutil
from typing import Any
from uuid import uuid4

from app.context.manager import ContextManager


CONTEXT_DEFAULTS = {
    "AGENTS.md": "# AGENTS\nOpenLong workspace operating notes.\n- Stay inside the workspace.\n- Use tools only when needed.\n- Prefer concise Simplified Chinese replies unless the user asks otherwise.",
    "USER.md": "# USER\nDescribe user profile and preferences.",
    "SOUL.md": "# SOUL\nDescribe agent personality and behavior.",
    "IDENTITY.md": "# IDENTITY\nDescribe agent role and scope.",
    "RULES.md": "# RULES\nList non-negotiable rules.",
    "STYLE.md": "# STYLE\nDefine response style and format.",
    "TOOLS.md": "# TOOLS\nRuntime will sync the available tools here.",
    "HEARTBEAT.md": "# HEARTBEAT\nRuntime will sync the latest agent status here.",
    "BOOTSTRAP.md": "# BOOTSTRAP\nOn the first successful turn, summarize the user intent into USER.md and then remove this file.",
    "MEMORY.md": "# MEMORY\nPersistent memory index for this agent.",
}

WORKSPACE_DIRECTORIES = [
    "skills",
    "memory/logs",
    "memory/summaries",
    "logs",
]

WORKSPACE_METADATA_FILE = "workspace.json"
WORKSPACE_STATE_FILE = "state.json"
WORKSPACE_EVENT_LOG = "logs/events.jsonl"
WORKSPACE_EXPORT_DIR = "_exports"
WORKSPACE_TEMPLATE_DIR = "_templates"
BOOTSTRAP_FILE = "BOOTSTRAP.md"
UPLOADS_DIR = "uploads"
_SAFE_UPLOAD_NAME = re.compile(r"[^A-Za-z0-9._-]+")

SKILL_LAYOUT_README = """# Skills Directory Layout

Each skill is a standalone folder:

skills/
  <skill_id>/
    SKILL.md
    script.py (optional)

SKILL.md standard sections:
- 技能说明
- 触发条件
- 参数说明
- 示例
"""

WORKSPACE_TEMPLATES: dict[str, dict[str, Any]] = {
    "default": {
        "description": "Base agent workspace.",
        "files": {},
    },
    "coding": {
        "description": "Coding-oriented agent workspace.",
        "files": {
            "IDENTITY.md": "# IDENTITY\nYou are a coding agent focused on implementation, debugging, and delivery.",
            "SOUL.md": "# SOUL\nBe pragmatic, direct, and precise when solving engineering tasks.",
            "STYLE.md": "# STYLE\nPrefer concise technical replies with clear next actions.",
        },
    },
    "research": {
        "description": "Research-oriented agent workspace.",
        "files": {
            "IDENTITY.md": "# IDENTITY\nYou are a research agent focused on gathering, comparing, and summarizing evidence.",
            "SOUL.md": "# SOUL\nBe careful with assumptions and surface tradeoffs explicitly.",
            "STYLE.md": "# STYLE\nSummarize findings first, then add supporting detail.",
        },
    },
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkspaceManager:
    def __init__(self, workspace_root: str, project_root: str | None = None) -> None:
        default_project_root = Path(__file__).resolve().parents[4]
        self._project_root = Path(project_root).resolve() if project_root else default_project_root
        self._workspace_root = (self._project_root / workspace_root).resolve()
        self._workspace_root.mkdir(parents=True, exist_ok=True)
        (self._workspace_root / WORKSPACE_EXPORT_DIR).mkdir(parents=True, exist_ok=True)
        (self._workspace_root / WORKSPACE_TEMPLATE_DIR).mkdir(parents=True, exist_ok=True)
        self._context_manager = ContextManager()

    @property
    def workspace_root(self) -> Path:
        return self._workspace_root

    @property
    def project_root(self) -> Path:
        return self._project_root

    def workspace_exists(self, agent_id: str) -> bool:
        return self._workspace_path(agent_id).exists()

    def ensure_agent_workspace(
        self,
        agent_id: str,
        template_name: str = "default",
        agent_type: str = "general",
    ) -> Path:
        self.create_workspace(agent_id=agent_id, template_name=template_name, agent_type=agent_type)
        return self._workspace_path(agent_id)

    def create_workspace(
        self,
        *,
        agent_id: str,
        template_name: str = "default",
        agent_type: str = "general",
        overwrite: bool = False,
    ) -> dict[str, Any]:
        workspace = self._workspace_path(agent_id)
        existing_metadata = self._read_json(self._metadata_path(agent_id))
        existing_state = self._read_json(self._state_path(agent_id))
        if overwrite and workspace.exists():
            shutil.rmtree(workspace)
            self._context_manager.invalidate(workspace)
            existing_metadata = {}
            existing_state = {}

        workspace.mkdir(parents=True, exist_ok=True)
        for relative_dir in WORKSPACE_DIRECTORIES:
            (workspace / relative_dir).mkdir(parents=True, exist_ok=True)

        resolved_template_name = str(existing_metadata.get("template_name") or template_name)
        resolved_agent_type = str(
            existing_state.get("agent_type")
            or existing_metadata.get("agent_type")
            or agent_type
        )
        template = self._resolve_template(resolved_template_name)
        files = dict(CONTEXT_DEFAULTS)
        files.update(template["files"])
        if existing_metadata.get("bootstrap_status") == "completed":
            files.pop(BOOTSTRAP_FILE, None)

        for filename, content in files.items():
            path = workspace / filename
            if overwrite or not path.exists():
                path.write_text(content.rstrip() + "\n", encoding="utf-8")

        skill_readme = workspace / "skills" / "README.md"
        if overwrite or not skill_readme.exists():
            skill_readme.write_text(SKILL_LAYOUT_README, encoding="utf-8")

        created_at = existing_metadata.get("created_at") if existing_metadata and not overwrite else _utc_now().isoformat()
        metadata = {
            "agent_id": agent_id,
            "agent_type": resolved_agent_type,
            "template_name": resolved_template_name,
            "created_at": created_at,
            "updated_at": _utc_now().isoformat(),
            "bootstrap_status": existing_metadata.get("bootstrap_status", "pending") if not overwrite else "pending",
            "bootstrap_completed_at": existing_metadata.get("bootstrap_completed_at") if not overwrite else None,
            "directories": list(WORKSPACE_DIRECTORIES),
            "files": sorted(files.keys()),
            "version": 2,
        }
        if existing_metadata.get("bootstrap_notes") and not overwrite:
            metadata["bootstrap_notes"] = existing_metadata["bootstrap_notes"]
        self._write_json(self._metadata_path(agent_id), metadata)

        state = existing_state
        if overwrite or not state:
            state = {
                "agent_id": agent_id,
                "agent_type": resolved_agent_type,
                "current_task": None,
                "last_active_at": _utc_now().isoformat(),
                "workspace_template": resolved_template_name,
            }
            self._write_json(self._state_path(agent_id), state)

        event_log = workspace / WORKSPACE_EVENT_LOG
        event_log.parent.mkdir(parents=True, exist_ok=True)
        if overwrite or not event_log.exists():
            event_log.write_text("", encoding="utf-8")

        return self.load_workspace(agent_id=agent_id, create_if_missing=False)

    def load_workspace(self, agent_id: str, create_if_missing: bool = True) -> dict[str, Any]:
        workspace = self._workspace_path(agent_id)
        if not workspace.exists():
            if not create_if_missing:
                return {
                    "agent_id": agent_id,
                    "exists": False,
                    "path": str(workspace),
                }
            self.create_workspace(agent_id=agent_id)

        metadata = self._read_json(self._metadata_path(agent_id))
        state = self._read_json(self._state_path(agent_id))
        files = sorted(path.name for path in workspace.iterdir() if path.is_file())
        directories = sorted(path.name for path in workspace.iterdir() if path.is_dir())

        return {
            "agent_id": agent_id,
            "exists": True,
            "path": str(workspace),
            "bootstrap_pending": (workspace / BOOTSTRAP_FILE).exists(),
            "metadata": metadata,
            "state": state,
            "files": files,
            "directories": directories,
        }

    def list_workspaces(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted(self._workspace_root.iterdir(), key=lambda item: item.name):
            if not path.is_dir():
                continue
            if path.name.startswith("_"):
                continue
            items.append(self.load_workspace(path.name, create_if_missing=False))
        return items

    def delete_workspace(self, agent_id: str, force: bool = False) -> dict[str, Any]:
        if agent_id == "main" and not force:
            return {"agent_id": agent_id, "deleted": False, "reason": "main workspace requires force"}

        workspace = self._workspace_path(agent_id)
        if not workspace.exists():
            return {"agent_id": agent_id, "deleted": False, "reason": "workspace not found"}

        shutil.rmtree(workspace)
        self._context_manager.invalidate(workspace)
        return {"agent_id": agent_id, "deleted": True}

    def list_templates(self) -> dict[str, Any]:
        return {
            "templates": [
                {"name": name, "description": template["description"]}
                for name, template in sorted(WORKSPACE_TEMPLATES.items())
            ]
        }

    def export_workspace(self, agent_id: str, export_dir: str | None = None) -> dict[str, Any]:
        workspace = self.ensure_agent_workspace(agent_id)
        export_root = Path(export_dir).resolve() if export_dir else (self._workspace_root / WORKSPACE_EXPORT_DIR)
        export_root.mkdir(parents=True, exist_ok=True)

        archive_stem = export_root / f"{agent_id}-{_utc_now().strftime('%Y%m%d%H%M%S')}"
        archive_path = shutil.make_archive(str(archive_stem), "zip", root_dir=str(workspace.parent), base_dir=workspace.name)
        return {
            "agent_id": agent_id,
            "archive_path": archive_path,
        }

    def import_workspace(self, agent_id: str, archive_path: str, overwrite: bool = False) -> dict[str, Any]:
        archive = Path(archive_path).resolve()
        if not archive.exists():
            raise FileNotFoundError(f"archive not found: {archive_path}")

        target = self._workspace_path(agent_id)
        if target.exists():
            if not overwrite:
                raise FileExistsError(f"workspace already exists: {agent_id}")
            shutil.rmtree(target)

        staging = self._workspace_root / WORKSPACE_EXPORT_DIR / f"restore-{uuid4().hex}"
        staging.mkdir(parents=True, exist_ok=True)
        try:
            shutil.unpack_archive(str(archive), str(staging))
            candidates = [item for item in staging.iterdir() if item.is_dir()]
            if not candidates:
                raise FileNotFoundError("no workspace directory found in archive")
            source = candidates[0]
            shutil.move(str(source), str(target))
        finally:
            if staging.exists():
                shutil.rmtree(staging)

        self._rewrite_identity_files(agent_id)
        self._context_manager.invalidate(target)
        return self.load_workspace(agent_id=agent_id, create_if_missing=False)

    def load_context_block(self, agent_id: str, force_refresh: bool = False) -> str:
        workspace = self.ensure_agent_workspace(agent_id)
        return self._context_manager.build_context(workspace, force_refresh=force_refresh)

    def get_context_snapshot(self, agent_id: str, force_refresh: bool = False) -> dict[str, Any]:
        workspace = self.ensure_agent_workspace(agent_id)
        snapshot = self._context_manager.load(workspace, force_refresh=force_refresh)
        return snapshot.to_dict()

    def update_context(
        self,
        agent_id: str,
        context_name: str,
        content: str,
        dynamic_only: bool = True,
    ) -> dict[str, Any]:
        workspace = self.ensure_agent_workspace(agent_id)
        snapshot = self._context_manager.update_context(
            workspace_path=workspace,
            context_name=context_name,
            content=content,
            dynamic_only=dynamic_only,
        )
        self._touch_metadata(agent_id)
        return snapshot.to_dict()

    def context_cache_stats(self) -> dict[str, int]:
        return self._context_manager.cache_stats()

    def save_agent_state(self, agent_id: str, state: dict[str, Any]) -> dict[str, Any]:
        self.ensure_agent_workspace(agent_id)
        current = self._read_json(self._state_path(agent_id))
        current.update(state)
        current["agent_id"] = agent_id
        current["last_active_at"] = _utc_now().isoformat()
        self._write_json(self._state_path(agent_id), current)
        self._touch_metadata(agent_id)
        return current

    def has_workspace_file(self, agent_id: str, filename: str) -> bool:
        workspace = self.ensure_agent_workspace(agent_id)
        return (workspace / filename).exists()

    def write_workspace_file(self, agent_id: str, filename: str, content: str) -> str:
        workspace = self.ensure_agent_workspace(agent_id)
        target = workspace / filename
        normalized = content.rstrip()
        target.write_text((normalized + "\n") if normalized else "", encoding="utf-8")
        self._context_manager.invalidate(workspace)
        self._touch_metadata(agent_id)
        return str(target)

    def store_session_upload(
        self,
        agent_id: str,
        *,
        session_id: str,
        filename: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        workspace = self.ensure_agent_workspace(agent_id)
        uploads_dir = workspace / UPLOADS_DIR / self._normalize_path_token(session_id)
        uploads_dir.mkdir(parents=True, exist_ok=True)

        original_name = filename.strip() or "upload.bin"
        normalized_name = self._safe_upload_name(original_name)
        target = self._unique_upload_path(uploads_dir, normalized_name)
        target.write_bytes(content)

        relative_path = target.relative_to(workspace).as_posix()
        stat = target.stat()
        checksum = sha256(content).hexdigest()
        self._touch_metadata(agent_id)
        return {
            "agent_id": agent_id,
            "session_id": session_id,
            "filename": original_name,
            "saved_name": target.name,
            "relative_path": relative_path,
            "absolute_path": str(target),
            "content_type": content_type or "application/octet-stream",
            "size": stat.st_size,
            "sha256": checksum,
            "uploaded_at": _utc_now().isoformat(),
        }

    def list_session_uploads(self, agent_id: str, *, session_id: str) -> list[dict[str, Any]]:
        workspace = self.ensure_agent_workspace(agent_id)
        uploads_dir = workspace / UPLOADS_DIR / self._normalize_path_token(session_id)
        if not uploads_dir.exists():
            return []

        items: list[dict[str, Any]] = []
        for path in sorted(uploads_dir.iterdir(), key=lambda item: item.name):
            if not path.is_file():
                continue
            stat = path.stat()
            content_type, _ = mimetypes.guess_type(path.name)
            items.append(
                {
                    "agent_id": agent_id,
                    "session_id": session_id,
                    "saved_name": path.name,
                    "filename": path.name,
                    "relative_path": path.relative_to(workspace).as_posix(),
                    "absolute_path": str(path),
                    "content_type": content_type or "application/octet-stream",
                    "size": stat.st_size,
                    "uploaded_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                }
            )
        return items

    def get_session_upload_path(self, agent_id: str, *, session_id: str, saved_name: str) -> Path | None:
        workspace = self.ensure_agent_workspace(agent_id)
        uploads_dir = workspace / UPLOADS_DIR / self._normalize_path_token(session_id)
        if not uploads_dir.exists():
            return None

        candidate = uploads_dir / Path(saved_name).name
        if not candidate.exists() or not candidate.is_file():
            return None
        return candidate

    def delete_workspace_file(self, agent_id: str, filename: str) -> bool:
        workspace = self.ensure_agent_workspace(agent_id)
        target = workspace / filename
        if not target.exists():
            return False
        target.unlink()
        self._context_manager.invalidate(workspace)
        self._touch_metadata(agent_id)
        return True

    def complete_bootstrap(self, agent_id: str, *, user_message: str, assistant_reply: str) -> bool:
        if not self.delete_workspace_file(agent_id, BOOTSTRAP_FILE):
            return False

        metadata = self._read_json(self._metadata_path(agent_id))
        metadata["bootstrap_status"] = "completed"
        metadata["bootstrap_completed_at"] = _utc_now().isoformat()
        metadata["bootstrap_notes"] = {
            "first_user_message": user_message[:400],
            "first_assistant_reply": assistant_reply[:400],
        }
        self._write_json(self._metadata_path(agent_id), metadata)
        return True

    def load_agent_state(self, agent_id: str) -> dict[str, Any]:
        self.ensure_agent_workspace(agent_id)
        return self._read_json(self._state_path(agent_id))

    def append_log(
        self,
        agent_id: str,
        *,
        event_name: str,
        message: str,
        session_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        workspace = self.ensure_agent_workspace(agent_id)
        log_file = workspace / WORKSPACE_EVENT_LOG
        record = {
            "timestamp": _utc_now().isoformat(),
            "agent_id": agent_id,
            "session_id": session_id,
            "event_name": event_name,
            "message": message,
            "payload": payload or {},
        }
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def recent_logs(self, agent_id: str, limit: int = 100) -> list[dict[str, Any]]:
        workspace = self.ensure_agent_workspace(agent_id)
        log_file = workspace / WORKSPACE_EVENT_LOG
        if not log_file.exists():
            return []

        rows: list[dict[str, Any]] = []
        for line in log_file.read_text(encoding="utf-8").splitlines():
            payload = line.strip()
            if not payload:
                continue
            try:
                rows.append(json.loads(payload))
            except json.JSONDecodeError:
                continue
        return rows[-limit:][::-1]

    def _workspace_path(self, agent_id: str) -> Path:
        return self._workspace_root / agent_id

    def _safe_upload_name(self, filename: str) -> str:
        base = Path(filename).name.strip() or "upload.bin"
        if "." in base:
            stem = Path(base).stem
            suffix = Path(base).suffix[:16]
        else:
            stem = base
            suffix = ""

        safe_stem = _SAFE_UPLOAD_NAME.sub("_", stem).strip("._") or "upload"
        return f"{safe_stem[:80]}{suffix}"

    def _unique_upload_path(self, parent: Path, filename: str) -> Path:
        candidate = parent / filename
        if not candidate.exists():
            return candidate

        stem = candidate.stem
        suffix = candidate.suffix
        for index in range(1, 1000):
            next_candidate = parent / f"{stem}_{index}{suffix}"
            if not next_candidate.exists():
                return next_candidate

        return parent / f"{stem}_{uuid4().hex[:8]}{suffix}"

    def _normalize_path_token(self, value: str) -> str:
        normalized = _SAFE_UPLOAD_NAME.sub("_", value.strip()).strip("._")
        return normalized or "default"

    def _metadata_path(self, agent_id: str) -> Path:
        return self._workspace_path(agent_id) / WORKSPACE_METADATA_FILE

    def _state_path(self, agent_id: str) -> Path:
        return self._workspace_path(agent_id) / WORKSPACE_STATE_FILE

    def _resolve_template(self, template_name: str) -> dict[str, Any]:
        template = WORKSPACE_TEMPLATES.get(template_name)
        if template is None:
            raise ValueError(f"workspace template not found: {template_name}")
        return template

    def _touch_metadata(self, agent_id: str) -> None:
        metadata = self._read_json(self._metadata_path(agent_id))
        if not metadata:
            return
        metadata["updated_at"] = _utc_now().isoformat()
        self._write_json(self._metadata_path(agent_id), metadata)

    def _rewrite_identity_files(self, agent_id: str) -> None:
        metadata_path = self._metadata_path(agent_id)
        state_path = self._state_path(agent_id)
        metadata = self._read_json(metadata_path)
        if metadata:
            metadata["agent_id"] = agent_id
            metadata["updated_at"] = _utc_now().isoformat()
            self._write_json(metadata_path, metadata)
        state = self._read_json(state_path)
        if state:
            state["agent_id"] = agent_id
            state["last_active_at"] = _utc_now().isoformat()
            self._write_json(state_path, state)

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
