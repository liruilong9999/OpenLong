import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import load_settings
from app.core.events import EventBus
from app.main import create_app
from app.tools.builtins.file_tool import FileTool
from app.tools.builtins.shell_tool import ShellTool
from app.tools.executor import ToolExecutor
from app.tools.permissions import ToolPermissionManager
from app.tools.registry import ToolRegistry
from app.workspace.manager import WorkspaceManager


def _create_client(monkeypatch, tmp_path: Path) -> TestClient:
    load_settings.cache_clear()
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("OPENLONG_DISABLE_MODEL_API", "1")
    monkeypatch.setenv("TOOL_SHELL_ENABLED", "true")
    return TestClient(create_app())


def test_shell_approval_api_flow(monkeypatch, tmp_path: Path) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        create_resp = client.post("/sessions", json={"session_id": "approval-s1", "agent_id": "main"})
        assert create_resp.status_code == 200

        shell_resp = client.post(
            "/tasks/tool",
            json={
                "tool_name": "shell",
                "session_id": "approval-s1",
                "agent_id": "main",
                "confirm": False,
                "args": {"input": "echo approval-ok"},
            },
        )
        assert shell_resp.status_code == 200
        payload = shell_resp.json()
        assert payload["data"]["pending_approval"] is True

        approval_id = payload["data"]["approval"]["approval_id"]

        approvals_resp = client.get("/tools/approvals")
        assert approvals_resp.status_code == 200
        assert any(item["approval_id"] == approval_id for item in approvals_resp.json()["items"])

        approve_resp = client.post(f"/tools/approvals/{approval_id}/approve", json={})
        assert approve_resp.status_code == 200
        approved = approve_resp.json()
        assert approved["status"] == "executed"
        assert "approval-ok" in (approved["result"] or {}).get("content", "")

        system_resp = client.get("/dashboard/system")
        assert system_resp.status_code == 200
        system_payload = system_resp.json()
        assert system_payload["tool_approvals"]["stats"]["pending"] == 0
        assert system_payload["shell_logs"]["items"]
        assert system_payload["shell_logs"]["items"][0]["result_data"]["exit_code"] == 0


def test_shell_executor_supports_cwd_and_stream_output(tmp_path: Path) -> None:
    workspace_manager = WorkspaceManager(str(tmp_path / "workspace"), project_root=str(tmp_path / "project"))
    registry = ToolRegistry()
    registry.register(FileTool(workspace_manager))
    registry.register(
        ShellTool(
            enabled=True,
            project_root=workspace_manager.project_root,
            workspace_root=workspace_manager.workspace_root,
        )
    )
    event_bus = EventBus()
    executor = ToolExecutor(
        registry,
        event_bus=event_bus,
        permission_manager=ToolPermissionManager(
            allowlist={"file", "shell"},
            denylist=set(),
            confirmation_required={"shell"},
        ),
    )

    streamed: list[str] = []
    event_bus.subscribe("tool.execution.stream", lambda event: streamed.append(str(event.payload.get("text") or "").strip()))

    result = asyncio.run(
        executor.execute(
            "shell",
            session_id="stream-s1",
            agent_id="main",
            caller="agent",
            confirm=True,
            input='python -c "import os; print(os.getcwd()); print(123)"',
            cwd="build-area",
            cwd_scope="project",
        )
    )

    assert result.success is True
    assert result.data["category"] == "build"
    assert result.data["exit_code"] == 0
    assert Path(result.data["cwd"]).name == "build-area"
    assert any("123" in item for item in streamed)


def test_shell_approval_can_be_rejected(monkeypatch, tmp_path: Path) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        create_resp = client.post("/sessions", json={"session_id": "approval-reject-s1", "agent_id": "main"})
        assert create_resp.status_code == 200

        shell_resp = client.post(
            "/tasks/tool",
            json={
                "tool_name": "shell",
                "session_id": "approval-reject-s1",
                "agent_id": "main",
                "confirm": False,
                "args": {"input": "echo reject-me"},
            },
        )
        approval_id = shell_resp.json()["data"]["approval"]["approval_id"]

        reject_resp = client.post(
            f"/tools/approvals/{approval_id}/reject",
            json={"reason": "user rejected"},
        )
        assert reject_resp.status_code == 200
        rejected = reject_resp.json()
        assert rejected["status"] == "rejected"
        assert rejected["decision_reason"] == "user rejected"

