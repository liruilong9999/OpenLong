from fastapi.testclient import TestClient

from app.main import create_app


def _recv_until_reply(ws, max_events: int = 20) -> dict:
    for _ in range(max_events):
        payload = ws.receive_json()
        if payload.get("type") == "chat.reply":
            return payload
    raise AssertionError("chat.reply not received from websocket")


def test_gateway_chat_session_and_dashboard() -> None:
    client = TestClient(create_app())

    create_resp = client.post("/sessions", json={})
    assert create_resp.status_code == 200
    session_id = create_resp.json()["session_id"]

    chat_resp = client.post("/chat", json={"session_id": session_id, "message": "hello gateway"})
    assert chat_resp.status_code == 200
    payload = chat_resp.json()
    assert payload["session_id"] == session_id
    assert payload["agent_id"]
    assert payload["task_id"]

    history_resp = client.get(f"/sessions/{session_id}/history")
    assert history_resp.status_code == 200
    history = history_resp.json()
    assert len(history) >= 2
    assert history[-1]["role"] == "assistant"

    agents_resp = client.get("/dashboard/agents")
    assert agents_resp.status_code == 200
    assert any(item["agent_id"] == "main" for item in agents_resp.json())

    sessions_resp = client.get("/dashboard/sessions")
    assert sessions_resp.status_code == 200
    assert any(item["session_id"] == session_id for item in sessions_resp.json())

    logs_resp = client.get("/dashboard/logs", params={"limit": 20})
    assert logs_resp.status_code == 200
    assert any(item["name"] == "user.input.received" for item in logs_resp.json())

    tasks_resp = client.get("/dashboard/tasks")
    assert tasks_resp.status_code == 200
    assert tasks_resp.json()["stats"]["total"] >= 1


def test_gateway_tool_task_and_websocket() -> None:
    client = TestClient(create_app())

    create_resp = client.post("/sessions", json={"session_id": "ws-test"})
    assert create_resp.status_code == 200

    tool_write = client.post(
        "/tasks/tool",
        json={
            "tool_name": "file",
            "session_id": "ws-test",
            "agent_id": "main",
            "args": {"action": "write", "path": "notes/demo.txt", "content": "ok"},
        },
    )
    assert tool_write.status_code == 200
    assert tool_write.json()["success"] is True

    tool_read = client.post(
        "/tasks/tool",
        json={
            "tool_name": "file",
            "session_id": "ws-test",
            "agent_id": "main",
            "args": {"action": "read", "path": "notes/demo.txt"},
        },
    )
    assert tool_read.status_code == 200
    assert tool_read.json()["success"] is True
    assert "ok" in tool_read.json()["content"]

    with client.websocket_connect("/ws/ws-test") as ws:
        connected = ws.receive_json()
        assert connected["type"] == "ws.connected"

        ws.send_json({"message": "hello websocket"})
        reply = _recv_until_reply(ws)
        assert reply["session_id"] == "ws-test"
        assert reply["reply"]
