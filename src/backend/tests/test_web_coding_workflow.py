from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import load_settings
from app.main import create_app


def _create_client(monkeypatch, tmp_path: Path) -> TestClient:
    load_settings.cache_clear()
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("OPENLONG_DISABLE_MODEL_API", "1")
    return TestClient(create_app())


def test_web_chat_can_create_directory_write_code_and_read_back(monkeypatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)

    session_resp = client.post("/sessions", json={"session_id": "web-coding-s1", "agent_id": "main"})
    assert session_resp.status_code == 200

    mkdir_resp = client.post(
        "/chat",
        json={"session_id": "web-coding-s1", "agent_id": "main", "message": "创建目录 demoapp"},
    )
    assert mkdir_resp.status_code == 200
    assert "工具执行完成" in mkdir_resp.json()["reply"]
    assert "created dir: demoapp" in mkdir_resp.json()["reply"]

    write_resp = client.post(
        "/chat",
        json={
            "session_id": "web-coding-s1",
            "agent_id": "main",
            "message": '创建文件 "demoapp/main.py" 内容是 print("hello from web test")',
        },
    )
    assert write_resp.status_code == 200
    assert "工具执行完成" in write_resp.json()["reply"]
    assert "written: demoapp/main.py" in write_resp.json()["reply"]

    read_resp = client.post(
        "/chat",
        json={"session_id": "web-coding-s1", "agent_id": "main", "message": "/read demoapp/main.py"},
    )
    assert read_resp.status_code == 200
    assert "工具执行完成" in read_resp.json()["reply"]
    assert "hello from web test" in read_resp.json()["reply"]

    written_file = tmp_path / "workspace" / "main" / "demoapp" / "main.py"
    assert written_file.exists()
    assert written_file.read_text(encoding="utf-8") == 'print("hello from web test")'

    logs_resp = client.get("/tools/logs", params={"limit": 20})
    assert logs_resp.status_code == 200
    logs_payload = logs_resp.json()
    assert logs_payload["stats"]["total"] >= 3
    assert any(item["tool_name"] == "file" for item in logs_payload["items"])


def test_web_tool_shell_is_disabled_by_default(monkeypatch, tmp_path: Path) -> None:
    client = _create_client(monkeypatch, tmp_path)

    session_resp = client.post("/sessions", json={"session_id": "web-shell-s1", "agent_id": "main"})
    assert session_resp.status_code == 200

    shell_resp = client.post(
        "/tasks/tool",
        json={
            "tool_name": "shell",
            "session_id": "web-shell-s1",
            "agent_id": "main",
            "confirm": True,
            "args": {"input": "echo hello-from-shell"},
        },
    )
    assert shell_resp.status_code == 200
    payload = shell_resp.json()
    assert payload["success"] is False
    assert "disabled" in payload["content"]

