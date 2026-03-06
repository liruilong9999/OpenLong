from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import load_settings
from app.main import create_app


def _create_client(monkeypatch, tmp_path: Path) -> TestClient:
    load_settings.cache_clear()
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("OPENLONG_DISABLE_MODEL_API", "1")
    return TestClient(create_app())


def test_workspace_file_tree_read_and_save(monkeypatch, tmp_path: Path) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        tree_resp = client.get("/files/tree", params={"agent_id": "main", "scope": "workspace", "max_depth": 4})
        assert tree_resp.status_code == 200
        tree_payload = tree_resp.json()
        assert tree_payload["scope"] == "workspace"
        assert tree_payload["tree"]["type"] == "directory"

        save_resp = client.put(
            "/files/content",
            json={
                "agent_id": "main",
                "scope": "workspace",
                "path": "notes/ide-demo.txt",
                "content": "hello web ide",
            },
        )
        assert save_resp.status_code == 200
        assert save_resp.json()["scope"] == "workspace"

        read_resp = client.get(
            "/files/content",
            params={"agent_id": "main", "scope": "workspace", "path": "notes/ide-demo.txt"},
        )
        assert read_resp.status_code == 200
        assert read_resp.json()["content"] == "hello web ide"

        tree_after = client.get("/files/tree", params={"agent_id": "main", "scope": "workspace", "max_depth": 4})
        assert tree_after.status_code == 200
        notes_dir = next(item for item in tree_after.json()["tree"]["children"] if item["name"] == "notes")
        assert any(item["name"] == "ide-demo.txt" for item in notes_dir["children"])


def test_project_file_tree_can_browse_repo(monkeypatch, tmp_path: Path) -> None:
    with _create_client(monkeypatch, tmp_path) as client:
        tree_resp = client.get(
            "/files/tree",
            params={"agent_id": "main", "scope": "project", "root_path": "src/backend", "max_depth": 2},
        )
        assert tree_resp.status_code == 200
        payload = tree_resp.json()
        assert payload["scope"] == "project"
        assert payload["root_path"] == "src/backend"
        assert payload["tree"]["type"] == "directory"
        assert payload["tree"]["children"]

