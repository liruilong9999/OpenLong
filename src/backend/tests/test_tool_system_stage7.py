from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.tools.executor import ToolExecutor
from app.tools.permissions import ToolPermissionManager
from app.tools.registry import ToolRegistry
from app.tools.builtins.file_tool import FileTool
from app.tools.builtins.http_tool import HttpTool
from app.tools.builtins.shell_tool import ShellTool
from app.tools.builtins.time_tool import TimeTool
from app.tools.builtins.workspace_tool import WorkspaceTool
from app.workspace.manager import WorkspaceManager


def _build_executor(tmp_path: Path) -> ToolExecutor:
    workspace_manager = WorkspaceManager(str(tmp_path))
    registry = ToolRegistry()
    registry.register(FileTool(workspace_manager))
    registry.register(HttpTool())
    registry.register(ShellTool(enabled=True))
    registry.register(TimeTool())
    registry.register(WorkspaceTool(workspace_manager))
    permission_manager = ToolPermissionManager(
        allowlist={"file", "http", "shell", "time", "workspace"},
        denylist=set(),
        confirmation_required={"shell"},
    )
    return ToolExecutor(registry, permission_manager=permission_manager)


def test_tool_registry_and_specs(tmp_path: Path) -> None:
    executor = _build_executor(tmp_path)
    snapshot = executor._registry.snapshot()

    assert snapshot["count"] >= 5
    assert {item["name"] for item in snapshot["tools"]} == {"file", "http", "shell", "time", "workspace"}
    assert any(
        param["name"] == "path"
        for item in snapshot["tools"]
        if item["name"] == "file"
        for param in item["parameters"]
    )


def test_tool_permission_profile_resolution() -> None:
    manager = ToolPermissionManager.from_settings(
        profile="minimal",
        available_tools=["file", "http", "shell", "time", "workspace"],
        allowlist_csv="file",
        confirmation_csv="shell",
    )

    assert manager.profile == "minimal"
    assert manager.allowlist == {"workspace", "time", "file"}
    assert manager.requires_confirmation("shell") is True


def test_tool_executor_permissions_and_sandbox(tmp_path: Path) -> None:
    import asyncio

    executor = _build_executor(tmp_path)

    denied = asyncio.run(executor.execute("shell", input="echo hi", caller="agent", confirm=False))
    assert denied.success is False
    assert "requires confirmation" in denied.content

    traversal = asyncio.run(
        executor.execute(
            "file",
            action="read",
            path="../secret.txt",
            agent_id="main",
            session_id="s1",
        )
    )
    assert traversal.success is False
    assert "blocked" in traversal.content or "path" in traversal.content

    localhost = asyncio.run(
        executor.execute(
            "http",
            url="http://127.0.0.1:8000",
            session_id="s1",
            agent_id="main",
        )
    )
    assert localhost.success is False
    assert "blocked" in localhost.content


def test_tool_debug_api_and_logs() -> None:
    client = TestClient(create_app())

    tools_resp = client.get("/tools")
    assert tools_resp.status_code == 200
    tools_payload = tools_resp.json()
    assert tools_payload["count"] >= 5
    assert "permissions" in tools_payload
    assert "profile" in tools_payload["permissions"]

    write_resp = client.post(
        "/tools/debug/execute",
        json={
            "tool_name": "file",
            "session_id": "tool-debug-s1",
            "agent_id": "main",
            "caller": "debug",
            "args": {"action": "write", "path": "notes/tool.txt", "content": "ok"},
        },
    )
    assert write_resp.status_code == 200
    assert write_resp.json()["success"] is True

    shell_resp = client.post(
        "/tools/debug/execute",
        json={
            "tool_name": "shell",
            "session_id": "tool-debug-s1",
            "agent_id": "main",
            "caller": "debug",
            "confirm": False,
            "args": {"input": "echo hi"},
        },
    )
    assert shell_resp.status_code == 200
    assert shell_resp.json()["success"] is False

    logs_resp = client.get("/tools/logs", params={"limit": 20})
    assert logs_resp.status_code == 200
    logs_payload = logs_resp.json()
    assert logs_payload["stats"]["total"] >= 2
    assert logs_payload["items"]

    dashboard_resp = client.get("/dashboard/tools", params={"limit": 10})
    assert dashboard_resp.status_code == 200
    dash = dashboard_resp.json()
    assert "registry" in dash
    assert "logs" in dash
