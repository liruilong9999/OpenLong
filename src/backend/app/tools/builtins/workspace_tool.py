from __future__ import annotations

from pathlib import Path
from typing import Any

from app.tools.types import ToolParameterSpec, ToolResult, ToolSpec
from app.workspace.manager import WorkspaceManager


class WorkspaceTool:
    spec = ToolSpec(
        name="workspace",
        description="Inspect the agent workspace path and top-level contents.",
        parameters=[
            ToolParameterSpec(name="action", param_type="string", required=False, description="info or list", default="info"),
            ToolParameterSpec(name="agent_id", param_type="string", required=False, description="target agent workspace"),
        ],
        returns="workspace path and metadata",
    )

    def __init__(self, workspace_manager: WorkspaceManager) -> None:
        self._workspace_manager = workspace_manager

    async def run(self, **kwargs: Any) -> ToolResult:
        agent_id = str(kwargs.get("agent_id", "main"))
        action = str(kwargs.get("action", "info")).lower()
        snapshot = self._workspace_manager.load_workspace(agent_id=agent_id, create_if_missing=True)
        workspace_path = Path(snapshot["path"])

        if action == "list":
            items = sorted(path.name for path in workspace_path.iterdir())
            return ToolResult(
                success=True,
                content=(
                    f"workspace={workspace_path}\n"
                    f"items={', '.join(items)}"
                ),
                data={"path": str(workspace_path), "items": items},
            )

        return ToolResult(
            success=True,
            content=(
                f"workspace={workspace_path}\n"
                f"template={snapshot.get('metadata', {}).get('template_name', 'default')}\n"
                f"agent_type={snapshot.get('state', {}).get('agent_type', 'general')}"
            ),
            data={
                "path": str(workspace_path),
                "template_name": snapshot.get("metadata", {}).get("template_name", "default"),
                "agent_type": snapshot.get("state", {}).get("agent_type", "general"),
            },
        )
