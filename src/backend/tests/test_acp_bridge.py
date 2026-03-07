import asyncio
import json
from io import StringIO
from pathlib import Path

from app.acp_bridge import ACPBridge
from app.cli import build_parser
from app.core.config import load_settings
from app.gateway.runtime import GatewayRuntime


def _runtime(tmp_path: Path) -> GatewayRuntime:
    load_settings.cache_clear()
    import os

    os.environ["WORKSPACE_ROOT"] = str(tmp_path / "workspace")
    os.environ["OPENLONG_DISABLE_MODEL_API"] = "1"
    return GatewayRuntime.from_settings(load_settings())


def test_acp_bridge_prompt_list_and_reset(tmp_path: Path) -> None:
    async def scenario() -> None:
        runtime = _runtime(tmp_path)
        events: list[dict] = []
        bridge = ACPBridge(runtime, event_writer=events.append)

        init = await bridge.handle_request({"id": 1, "method": "initialize", "params": {"agentId": "main"}})
        assert init["ok"] is True

        new_session = await bridge.handle_request({"id": 2, "method": "newSession", "params": {"sessionId": "ide-1", "agentId": "main"}})
        assert new_session["ok"] is True
        gateway_session_id = new_session["result"]["gatewaySessionId"]

        prompt = await bridge.handle_request({"id": 3, "method": "prompt", "params": {"sessionId": "ide-1", "text": "hello acp"}})
        assert prompt["ok"] is True
        assert prompt["result"]["status"] == "accepted"
        run_id = prompt["result"]["runId"]

        await bridge.wait_for_runs()
        assert any(item["event"] == "prompt.result" and item["runId"] == run_id for item in events)

        listed = await bridge.handle_request({"id": 4, "method": "listSessions", "params": {}})
        assert listed["ok"] is True
        assert listed["result"]["sessions"][0]["gatewaySessionId"] == gateway_session_id

        reset = await bridge.handle_request({"id": 5, "method": "reset", "params": {"sessionId": "ide-1"}})
        assert reset["ok"] is True
        assert reset["result"]["status"] == "reset"
        assert reset["result"]["gatewaySessionId"] != gateway_session_id

    asyncio.run(scenario())


def test_acp_bridge_cancel_running_prompt(tmp_path: Path) -> None:
    class _SessionManager:
        def __init__(self):
            self._sessions = {}

        def get_session_snapshot(self, session_id):
            return self._sessions.get(session_id, {"updated_at": "2026-01-01T00:00:00+00:00", "status": "active", "message_count": 0})

        def close_session(self, session_id, reason="manual"):
            self._sessions[session_id] = {"updated_at": "2026-01-01T00:00:00+00:00", "status": "closed", "message_count": 0, "reason": reason}
            return True

    class _RuntimeStub:
        def __init__(self):
            self.session_manager = _SessionManager()

        def create_session(self, session_id=None, preferred_agent_id=None, metadata=None):
            payload = {
                "session_id": session_id,
                "agent_id": preferred_agent_id or "main",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
            self.session_manager._sessions[session_id] = {"updated_at": payload["updated_at"], "status": "active", "message_count": 0}
            return payload

        def assign_agent_to_session(self, session_id, agent_id):
            return {"session_id": session_id, "agent_id": agent_id}

        async def handle_user_message(self, **kwargs):
            await asyncio.sleep(10)
            return {"reply": "slow", "task_id": "t1", "session_id": kwargs["session_id"], "agent_id": kwargs.get("preferred_agent_id") or "main"}

        def close_session(self, session_id, reason="manual"):
            return self.session_manager.close_session(session_id, reason)

    async def scenario() -> None:
        runtime = _RuntimeStub()
        events: list[dict] = []
        bridge = ACPBridge(runtime, event_writer=events.append)

        await bridge.handle_request({"id": 1, "method": "newSession", "params": {"sessionId": "ide-cancel", "agentId": "main"}})
        prompt = await bridge.handle_request({"id": 2, "method": "prompt", "params": {"sessionId": "ide-cancel", "text": "cancel me"}})
        run_id = prompt["result"]["runId"]

        cancel = await bridge.handle_request({"id": 3, "method": "cancel", "params": {"runId": run_id}})
        assert cancel["ok"] is True
        assert cancel["result"]["status"] == "cancel_requested"

        await bridge.wait_for_runs()
        assert any(item["event"] == "prompt.cancelled" and item["runId"] == run_id for item in events)

    asyncio.run(scenario())


def test_acp_stdio_bridge_outputs_jsonl(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    bridge = ACPBridge(runtime)
    input_stream = StringIO(
        "\n".join(
            [
                json.dumps({"id": 1, "method": "initialize", "params": {"agentId": "main"}}),
                json.dumps({"id": 2, "method": "newSession", "params": {"sessionId": "ide-stdio"}}),
                json.dumps({"id": 3, "method": "listSessions", "params": {}}),
            ]
        )
        + "\n"
    )
    output_stream = StringIO()

    code = asyncio.run(bridge.run_stdio(input_stream, output_stream))
    assert code == 0

    lines = [json.loads(line) for line in output_stream.getvalue().splitlines() if line.strip()]
    assert len(lines) == 3
    assert lines[0]["ok"] is True
    assert lines[1]["result"]["sessionId"] == "ide-stdio"
    assert lines[2]["result"]["sessions"]


def test_cli_parser_supports_acp_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["acp", "--agent-id", "coding", "--session-prefix", "ide"])
    assert args.command == "acp"
    assert args.agent_id == "coding"
    assert args.session_prefix == "ide"
