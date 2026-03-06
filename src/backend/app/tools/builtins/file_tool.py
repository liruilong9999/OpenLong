from __future__ import annotations

from pathlib import Path
from typing import Any

from app.tools.types import ToolParameterSpec, ToolResult, ToolSpec
from app.workspace.manager import WorkspaceManager


class FileTool:
    spec = ToolSpec(
        name="file",
        description="Read or write files inside the agent workspace.",
        parameters=[
            ToolParameterSpec(name="action", param_type="string", required=True, description="read or write"),
            ToolParameterSpec(name="path", param_type="string", required=True, description="relative file path"),
            ToolParameterSpec(name="content", param_type="string", required=False, description="content when action=write"),
            ToolParameterSpec(name="agent_id", param_type="string", required=False, description="target agent workspace"),
        ],
        returns="file content or write status",
    )

    def __init__(self, workspace_manager: WorkspaceManager) -> None:
        self._workspace_manager = workspace_manager

    async def run(self, **kwargs: Any) -> ToolResult:
        agent_id = str(kwargs.get("agent_id", "main"))
        action = str(kwargs.get("action", "read")).lower()
        relative_path = str(kwargs.get("path", ""))

        if not relative_path:
            return ToolResult(success=False, content="missing file path")

        workspace = self._workspace_manager.ensure_agent_workspace(agent_id)
        target = (workspace / relative_path).resolve()

        if workspace.resolve() not in target.parents and target != workspace.resolve():
            return ToolResult(success=False, content="path escapes workspace")

        if action == "read":
            if not target.exists() or not target.is_file():
                return ToolResult(success=False, content="file not found")
            return ToolResult(success=True, content=target.read_text(encoding="utf-8"))

        if action == "write":
            content = str(kwargs.get("content", ""))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return ToolResult(success=True, content=f"written: {Path(relative_path).as_posix()}")

        return ToolResult(success=False, content=f"unsupported action: {action}")
