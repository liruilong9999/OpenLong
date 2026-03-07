from fastapi.testclient import TestClient

from app.main import create_app


def test_workspace_management_api_flow() -> None:
    client = TestClient(create_app())

    templates_resp = client.get("/workspaces/templates")
    assert templates_resp.status_code == 200
    assert templates_resp.json()["templates"]

    create_resp = client.post(
        "/workspaces/coding-ui",
        json={"template_name": "coding", "agent_type": "coding", "overwrite": True},
    )
    assert create_resp.status_code == 200
    assert create_resp.json()["metadata"]["template_name"] == "coding"

    current_resp = client.get("/workspaces/coding-ui")
    assert current_resp.status_code == 200
    assert current_resp.json()["exists"] is True

    list_resp = client.get("/workspaces")
    assert list_resp.status_code == 200
    assert any(item["agent_id"] == "coding-ui" for item in list_resp.json())

    logs_resp = client.get("/workspaces/coding-ui/logs", params={"limit": 20})
    assert logs_resp.status_code == 200
    assert logs_resp.json()["agent_id"] == "coding-ui"

    backup_resp = client.post("/workspaces/coding-ui/backup", json={"export_dir": None})
    assert backup_resp.status_code == 200
    archive_path = backup_resp.json()["archive_path"]
    assert archive_path

    restore_resp = client.post(
        "/workspaces/restore-ui/restore",
        json={"archive_path": archive_path, "overwrite": False},
    )
    assert restore_resp.status_code == 200
    assert restore_resp.json()["exists"] is True

