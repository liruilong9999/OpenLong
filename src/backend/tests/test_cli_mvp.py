import json
from pathlib import Path

from app import cli


def _base_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("OPENLONG_DISABLE_MODEL_API", "1")
    monkeypatch.setenv("TOOL_SHELL_ENABLED", "true")


def test_cli_health_json(monkeypatch, tmp_path: Path, capsys) -> None:
    _base_env(monkeypatch, tmp_path)

    code = cli.main(["health", "--json"])
    assert code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert "provider" in payload
    assert "model" in payload


def test_cli_chat_sessions_and_history(monkeypatch, tmp_path: Path, capsys) -> None:
    _base_env(monkeypatch, tmp_path)
    session_id = "cli-chat-s1"

    code = cli.main(["chat", "--message", "hello cli", "--session-id", session_id, "--agent-id", "main", "--json"])
    assert code == 0
    chat_payload = json.loads(capsys.readouterr().out)
    assert chat_payload["session_id"] == session_id
    assert chat_payload["reply"]

    code = cli.main(["sessions", "list", "--json"])
    assert code == 0
    sessions_payload = json.loads(capsys.readouterr().out)
    assert any(item["session_id"] == session_id for item in sessions_payload)

    code = cli.main(["sessions", "history", "--session-id", session_id, "--json"])
    assert code == 0
    history_payload = json.loads(capsys.readouterr().out)
    assert any(item["role"] == "user" for item in history_payload)
    assert any(item["role"] == "assistant" for item in history_payload)


def test_cli_tools_and_workspace(monkeypatch, tmp_path: Path, capsys) -> None:
    _base_env(monkeypatch, tmp_path)

    code = cli.main(["tools", "list", "--json"])
    assert code == 0
    tools_payload = json.loads(capsys.readouterr().out)
    assert tools_payload["count"] >= 5

    code = cli.main(
        [
            "tools",
            "run",
            "--tool-name",
            "file",
            "--session-id",
            "cli-tools-s1",
            "--agent-id",
            "main",
            "--args",
            '{"action":"write","path":"notes/cli.txt","content":"cli-ok"}',
            "--json",
        ]
    )
    assert code == 0
    tool_payload = json.loads(capsys.readouterr().out)
    assert tool_payload["success"] is True

    code = cli.main(["workspace", "show", "--agent-id", "main", "--json"])
    assert code == 0
    workspace_payload = json.loads(capsys.readouterr().out)
    assert workspace_payload["agent_id"] == "main"
    assert "notes" in workspace_payload["directories"]

    code = cli.main(["workspace", "list", "--json"])
    assert code == 0
    workspace_list = json.loads(capsys.readouterr().out)
    assert any(item["agent_id"] == "main" for item in workspace_list)


def test_cli_shell_and_doctor(monkeypatch, tmp_path: Path, capsys) -> None:
    _base_env(monkeypatch, tmp_path)

    code = cli.main(
        [
            "tools",
            "run",
            "--tool-name",
            "shell",
            "--session-id",
            "cli-shell-s1",
            "--agent-id",
            "main",
            "--confirm",
            "--args",
            '{"input":"echo cli-shell-ok"}',
            "--json",
        ]
    )
    assert code == 0
    shell_payload = json.loads(capsys.readouterr().out)
    assert shell_payload["success"] is True
    assert "cli-shell-ok" in shell_payload["content"]

    code = cli.main(["doctor", "--json"])
    assert code == 0
    doctor_payload = json.loads(capsys.readouterr().out)
    assert "status" in doctor_payload
    assert "checks" in doctor_payload
    assert "tool_count" in doctor_payload["checks"]

