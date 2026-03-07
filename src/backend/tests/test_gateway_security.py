import base64

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_settings
from app.main import create_app


def _reset(monkeypatch) -> None:
    load_settings.cache_clear()


def test_ready_doctor_and_logs_endpoints(monkeypatch, tmp_path) -> None:
    _reset(monkeypatch)
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("OPENLONG_DISABLE_MODEL_API", "1")

    client = TestClient(create_app())

    create_resp = client.post("/sessions", json={"session_id": "sec-s1", "agent_id": "main"})
    assert create_resp.status_code == 200

    ready_resp = client.get("/ready")
    assert ready_resp.status_code == 200
    assert ready_resp.json()["status"] == "ready"

    logs_resp = client.get("/logs", params={"limit": 20})
    assert logs_resp.status_code == 200
    assert any(item["name"] == "session.created" for item in logs_resp.json()["items"])

    doctor_resp = client.get("/doctor")
    assert doctor_resp.status_code == 200
    payload = doctor_resp.json()
    assert "auth" in payload
    assert "readiness" in payload


def test_token_auth_protects_gateway_routes(monkeypatch, tmp_path) -> None:
    _reset(monkeypatch)
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("GATEWAY_AUTH_MODE", "token")
    monkeypatch.setenv("GATEWAY_AUTH_TOKEN", "secret-token")
    monkeypatch.setenv("OPENLONG_DISABLE_MODEL_API", "1")

    client = TestClient(create_app())

    assert client.get("/health").status_code == 200
    assert client.get("/sessions").status_code == 401

    authed = client.get("/sessions", headers={"Authorization": "Bearer secret-token"})
    assert authed.status_code == 200


def test_password_auth_accepts_basic_auth(monkeypatch, tmp_path) -> None:
    _reset(monkeypatch)
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("GATEWAY_AUTH_MODE", "password")
    monkeypatch.setenv("GATEWAY_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("OPENLONG_DISABLE_MODEL_API", "1")

    client = TestClient(create_app())

    assert client.get("/sessions").status_code == 401

    encoded = base64.b64encode(b"user:secret-password").decode("ascii")
    authed = client.get("/sessions", headers={"Authorization": f"Basic {encoded}"})
    assert authed.status_code == 200


def test_invalid_gateway_auth_config_fails_fast(monkeypatch, tmp_path) -> None:
    _reset(monkeypatch)
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("GATEWAY_AUTH_MODE", "token")
    monkeypatch.delenv("GATEWAY_AUTH_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="gateway_auth_mode=token requires gateway_auth_token"):
        create_app()
    load_settings.cache_clear()
