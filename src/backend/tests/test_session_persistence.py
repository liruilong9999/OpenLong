from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import load_settings
from app.gateway.session_manager import SessionManager
from app.main import create_app


def _create_client(monkeypatch, tmp_path: Path) -> TestClient:
    load_settings.cache_clear()
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("OPENLONG_DISABLE_MODEL_API", "1")
    return TestClient(create_app())


def test_sessions_survive_app_restart(monkeypatch, tmp_path: Path) -> None:
    session_id = "persist-s1"
    active_session_id = "persist-active-s1"

    with _create_client(monkeypatch, tmp_path) as client:
        create_resp = client.post(
            "/sessions",
            json={"session_id": session_id, "agent_id": "main", "metadata": {"tag": "persisted"}},
        )
        assert create_resp.status_code == 200

        chat_resp = client.post(
            "/chat",
            json={"session_id": session_id, "agent_id": "main", "message": "hello persistence"},
        )
        assert chat_resp.status_code == 200

        active_chat_resp = client.post(
            "/chat",
            json={"session_id": active_session_id, "agent_id": "main", "message": "still active"},
        )
        assert active_chat_resp.status_code == 200

        close_resp = client.post(f"/sessions/{session_id}/close", json={"reason": "restart-test"})
        assert close_resp.status_code == 200
        assert close_resp.json()["closed"] is True

        snapshot = client.get(f"/sessions/{session_id}")
        assert snapshot.status_code == 200
        assert snapshot.json()["status"] == "closed"

    session_files = list((tmp_path / "workspace" / "_sessions").glob("*.json"))
    assert session_files

    with _create_client(monkeypatch, tmp_path) as restarted_client:
        sessions_resp = restarted_client.get("/dashboard/sessions")
        assert sessions_resp.status_code == 200
        session_items = sessions_resp.json()
        restored = next(item for item in session_items if item["session_id"] == session_id)
        assert restored["status"] == "closed"
        assert restored["message_count"] >= 2

        active_restored = next(item for item in session_items if item["session_id"] == active_session_id)
        assert active_restored["status"] == "active"
        assert active_restored["message_count"] >= 2

        snapshot_resp = restarted_client.get(f"/sessions/{session_id}")
        assert snapshot_resp.status_code == 200
        snapshot_payload = snapshot_resp.json()
        assert snapshot_payload["metadata"]["tag"] == "persisted"
        assert snapshot_payload["metadata"]["close_reason"] == "restart-test"

        history_resp = restarted_client.get(f"/sessions/{session_id}/history")
        assert history_resp.status_code == 200
        history = history_resp.json()
        assert any(item["role"] == "user" and "hello persistence" in item["content"] for item in history)
        assert any(item["role"] == "assistant" for item in history)

        active_history_resp = restarted_client.get(f"/sessions/{active_session_id}/history")
        assert active_history_resp.status_code == 200
        active_history = active_history_resp.json()
        assert any(item["role"] == "user" and "still active" in item["content"] for item in active_history)

        agents_resp = restarted_client.get("/dashboard/agents")
        assert agents_resp.status_code == 200
        main_agent = next(item for item in agents_resp.json() if item["agent_id"] == "main")
        assert main_agent["active_sessions"] >= 1


def test_session_manager_ignores_corrupt_session_files(tmp_path: Path) -> None:
    storage_dir = tmp_path / "sessions"
    storage_dir.mkdir(parents=True, exist_ok=True)
    (storage_dir / "broken.json").write_text("{not-json", encoding="utf-8")

    manager = SessionManager(storage_dir=storage_dir)

    assert manager.list_sessions(include_closed=True) == []
