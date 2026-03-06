from __future__ import annotations

from pathlib import Path
from typing import Any

from app.tools.types import ToolParameterSpec, ToolResult, ToolSpec
from app.workspace.manager import WorkspaceManager


class FileTool:
    spec = ToolSpec(
        name="file",
        description="Read, write, or create directories inside the agent workspace or current project.",
        parameters=[
            ToolParameterSpec(name="action", param_type="string", required=True, description="read, write, or mkdir"),
            ToolParameterSpec(name="path", param_type="string", required=True, description="relative file or directory path"),
            ToolParameterSpec(name="content", param_type="string", required=False, description="content when action=write"),
            ToolParameterSpec(name="agent_id", param_type="string", required=False, description="target agent workspace"),
            ToolParameterSpec(name="scope", param_type="string", required=False, description="auto, workspace, or project", default="auto"),
        ],
        returns="file content, write status, or directory creation status",
    )

    def __init__(self, workspace_manager: WorkspaceManager) -> None:
        self._workspace_manager = workspace_manager

    async def run(self, **kwargs: Any) -> ToolResult:
        agent_id = str(kwargs.get("agent_id", "main"))
        action = str(kwargs.get("action", "read")).lower()
        relative_path = str(kwargs.get("path", ""))
        scope = str(kwargs.get("scope", "auto")).lower()

        if not relative_path:
            return ToolResult(success=False, content="missing file path")

        workspace = self._workspace_manager.ensure_agent_workspace(agent_id)
        target, resolved_scope = self._resolve_target(
            workspace=workspace,
            project_root=self._workspace_manager.project_root,
            relative_path=relative_path,
            action=action,
            scope=scope,
        )

        if target is None:
            return ToolResult(success=False, content="path escapes workspace")

        if action == "read":
            if not target.exists() or not target.is_file():
                return ToolResult(success=False, content="file not found")
            return ToolResult(
                success=True,
                content=target.read_text(encoding="utf-8"),
                data={"scope": resolved_scope, "path": str(target)},
            )

        if action == "write":
            content = str(kwargs.get("content", ""))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return ToolResult(
                success=True,
                content=f"written: {Path(relative_path).as_posix()}",
                data={"scope": resolved_scope, "path": str(target)},
            )

        if action == "mkdir":
            target.mkdir(parents=True, exist_ok=True)
            return ToolResult(
                success=True,
                content=f"created dir: {Path(relative_path).as_posix()}",
                data={"scope": resolved_scope, "path": str(target)},
            )

        return ToolResult(success=False, content=f"unsupported action: {action}")

    def _resolve_target(
        self,
        *,
        workspace: Path,
        project_root: Path,
        relative_path: str,
        action: str,
        scope: str,
    ) -> tuple[Path | None, str]:
        workspace_root = workspace.resolve()
        project_root = project_root.resolve()
        requested_path = Path(relative_path)

        if requested_path.is_absolute():
            resolved = requested_path.resolve()
            if self._is_within_root(resolved, workspace_root):
                return resolved, "workspace"
            if self._is_within_root(resolved, project_root):
                return resolved, "project"
            return None, scope

        if scope == "workspace":
            return self._safe_join(workspace_root, requested_path), "workspace"
        if scope == "project":
            return self._safe_join(project_root, requested_path), "project"

        project_candidate = self._safe_join(project_root, requested_path)
        workspace_candidate = self._safe_join(workspace_root, requested_path)
        if project_candidate is None or workspace_candidate is None:
            return None, scope

        if action == "read":
            if project_candidate.exists():
                return project_candidate, "project"
            if workspace_candidate.exists():
                return workspace_candidate, "workspace"
            if project_candidate.parent.exists() and len(requested_path.parts) > 1:
                return project_candidate, "project"
            return workspace_candidate, "workspace"

        if project_candidate.exists():
            return project_candidate, "project"
        if workspace_candidate.exists():
            return workspace_candidate, "workspace"
        if project_candidate.parent.exists() and len(requested_path.parts) > 1:
            return project_candidate, "project"
        return workspace_candidate, "workspace"

    def _safe_join(self, root: Path, path: Path) -> Path | None:
        target = (root / path).resolve()
        if not self._is_within_root(target, root):
            return None
        return target

    def _is_within_root(self, target: Path, root: Path) -> bool:
        return target == root or root in target.parents
