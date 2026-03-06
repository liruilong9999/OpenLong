import asyncio
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.agent.runtime import AgentRuntime
from app.main import create_app
from app.memory.manager import MemoryManager
from app.skills.loader import SkillLoader
from app.tools.builtins.file_tool import FileTool
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.workspace.manager import WorkspaceManager


def _settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        model_provider="OpenAI",
        openai_base_url="",
        openai_model="gpt-5.3",
        openai_api_key="",
        openai_reasoning_effort="medium",
        workspace_root=str(tmp_path),
    )


def _build_runtime(tmp_path: Path) -> AgentRuntime:
    workspace_manager = WorkspaceManager(str(tmp_path))
    memory_manager = MemoryManager(workspace_manager)
    skill_loader = SkillLoader(workspace_manager)
    registry = ToolRegistry()
    registry.register(FileTool(workspace_manager))
    tool_executor = ToolExecutor(registry)
    return AgentRuntime.from_settings(
        settings=_settings(tmp_path),
        workspace_manager=workspace_manager,
        memory_manager=memory_manager,
        skill_loader=skill_loader,
        tool_executor=tool_executor,
    )


def test_workspace_structure_and_templates(tmp_path: Path) -> None:
    manager = WorkspaceManager(str(tmp_path))
    snapshot = manager.create_workspace(
        agent_id="coder",
        template_name="coding",
        agent_type="coding",
    )

    assert snapshot["exists"] is True
    assert "skills" in snapshot["directories"]
    assert "logs" in snapshot["directories"]
    assert snapshot["metadata"]["template_name"] == "coding"
    assert snapshot["state"]["agent_type"] == "coding"

    workspace_path = Path(snapshot["path"])
    assert snapshot["bootstrap_pending"] is True
    assert (workspace_path / "USER.md").exists()
    assert (workspace_path / "SOUL.md").exists()
    assert (workspace_path / "AGENTS.md").exists()
    assert (workspace_path / "TOOLS.md").exists()
    assert (workspace_path / "HEARTBEAT.md").exists()
    assert (workspace_path / "BOOTSTRAP.md").exists()
    assert (workspace_path / "MEMORY.md").exists()
    assert (workspace_path / "skills" / "README.md").exists()
    assert "coding agent" in (workspace_path / "IDENTITY.md").read_text(encoding="utf-8").lower()


def test_workspace_persistence_backup_restore_and_logs(tmp_path: Path) -> None:
    manager = WorkspaceManager(str(tmp_path))
    created = manager.create_workspace(agent_id="agent-a", template_name="default")
    manager.update_context("agent-a", "USER", "用户：Alice", dynamic_only=True)
    manager.save_agent_state(
        "agent-a",
        {
            "agent_type": "general",
            "current_task": {
                "task_id": "task-1",
                "input_text": "hello",
                "status": "completed",
                "started_at": "2024-01-01T00:00:00+00:00",
                "finished_at": "2024-01-01T00:00:01+00:00",
                "error": None,
            },
        },
    )
    manager.append_log("agent-a", event_name="workspace.test", message="hello", payload={"x": 1})

    archive = manager.export_workspace("agent-a", export_dir=str(tmp_path / "exports"))
    restored = manager.import_workspace("agent-b", archive["archive_path"], overwrite=False)

    assert created["exists"] is True
    assert manager.load_agent_state("agent-a")["current_task"]["task_id"] == "task-1"
    assert manager.recent_logs("agent-a", limit=5)
    restored_path = Path(restored["path"])
    assert "Alice" in (restored_path / "USER.md").read_text(encoding="utf-8")
    assert (restored_path / "BOOTSTRAP.md").exists()

    delete_result = manager.delete_workspace("agent-b", force=True)
    assert delete_result["deleted"] is True
    main_delete = manager.delete_workspace("main", force=False)
    assert main_delete["deleted"] is False


def test_workspace_agent_runtime_restores_state(tmp_path: Path) -> None:
    manager = WorkspaceManager(str(tmp_path))
    manager.create_workspace(agent_id="restored-agent", template_name="coding", agent_type="coding")
    manager.save_agent_state(
        "restored-agent",
        {
            "agent_type": "coding",
            "current_task": {
                "task_id": "state-task",
                "input_text": "resume me",
                "status": "completed",
                "started_at": "2024-01-01T00:00:00+00:00",
                "finished_at": "2024-01-01T00:00:02+00:00",
                "error": None,
            },
        },
    )

    runtime = _build_runtime(tmp_path)
    agent = runtime.get_or_create("restored-agent")

    assert agent.agent_type == "coding"
    assert agent.current_task is not None
    assert agent.current_task.task_id == "state-task"


def test_workspace_bootstrap_completion() -> None:
    client = TestClient(create_app())

    create_resp = client.post(
        "/workspaces/bootstrap-agent",
        json={"template_name": "default", "agent_type": "general", "overwrite": True},
    )
    assert create_resp.status_code == 200
    assert create_resp.json()["bootstrap_pending"] is True

    chat_resp = client.post(
        "/chat",
        json={"session_id": "bootstrap-s1", "agent_id": "bootstrap-agent", "message": "以后请用中文并尽量简洁。"},
    )
    assert chat_resp.status_code == 200

    workspace_resp = client.get("/workspaces/bootstrap-agent")
    assert workspace_resp.status_code == 200
    workspace = workspace_resp.json()
    assert workspace["bootstrap_pending"] is False
    assert workspace["metadata"]["bootstrap_status"] == "completed"
    assert "BOOTSTRAP.md" not in workspace["files"]


def test_workspace_api_endpoints() -> None:
    client = TestClient(create_app())

    templates_resp = client.get("/workspaces/templates")
    assert templates_resp.status_code == 200
    assert templates_resp.json()["templates"]

    create_resp = client.post(
        "/workspaces/ws-stage8",
        json={"template_name": "coding", "agent_type": "coding", "overwrite": True},
    )
    assert create_resp.status_code == 200
    assert create_resp.json()["metadata"]["template_name"] == "coding"

    get_resp = client.get("/workspaces/ws-stage8")
    assert get_resp.status_code == 200
    assert get_resp.json()["exists"] is True

    backup_resp = client.post("/workspaces/ws-stage8/backup", json={})
    assert backup_resp.status_code == 200
    archive_path = backup_resp.json()["archive_path"]

    restore_resp = client.post(
        "/workspaces/ws-stage8-copy/restore",
        json={"archive_path": archive_path, "overwrite": True},
    )
    assert restore_resp.status_code == 200
    assert restore_resp.json()["exists"] is True

    logs_resp = client.get("/workspaces/ws-stage8/logs", params={"limit": 20})
    assert logs_resp.status_code == 200
    assert "items" in logs_resp.json()

    dashboard_resp = client.get("/dashboard/workspaces")
    assert dashboard_resp.status_code == 200
    assert "items" in dashboard_resp.json()
    assert "templates" in dashboard_resp.json()


def test_session_attachment_upload_persists_files() -> None:
    client = TestClient(create_app())

    create_resp = client.post("/sessions", json={"session_id": "upload-s1", "agent_id": "main"})
    assert create_resp.status_code == 200

    upload_resp = client.post(
        "/sessions/upload-s1/attachments",
        files=[
            ("files", ("notes.txt", b"hello-upload", "text/plain")),
            ("files", ("data.json", b'{"ok": true}', "application/json")),
        ],
        data={"agent_id": "main"},
    )
    assert upload_resp.status_code == 200
    payload = upload_resp.json()
    assert payload["session_id"] == "upload-s1"
    assert len(payload["items"]) == 2
    assert payload["items"][0]["relative_path"].startswith("uploads/upload-s1/")

    list_resp = client.get("/sessions/upload-s1/attachments")
    assert list_resp.status_code == 200
    listed = list_resp.json()["items"]
    assert len(listed) >= 2
    assert listed[0]["preview_url"].startswith("/sessions/upload-s1/attachments/")

    preview_resp = client.get(listed[0]["preview_url"])
    assert preview_resp.status_code == 200
    assert preview_resp.content

    workspace_resp = client.get("/workspaces/main")
    assert workspace_resp.status_code == 200
    workspace_path = Path(workspace_resp.json()["path"])
    assert (workspace_path / "uploads" / "upload-s1").exists()
    assert any(path.name.startswith("notes") for path in (workspace_path / "uploads" / "upload-s1").iterdir())
