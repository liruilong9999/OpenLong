from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Callable, TextIO
from uuid import uuid4

from app.gateway.runtime import GatewayRuntime


@dataclass(slots=True)
class ACPBridgeSession:
    session_id: str
    gateway_session_id: str
    agent_id: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "gatewaySessionId": self.gateway_session_id,
            "agentId": self.agent_id,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }


@dataclass(slots=True)
class ACPRun:
    run_id: str
    session_id: str
    gateway_session_id: str
    agent_id: str
    task: asyncio.Task[None]


class ACPBridge:
    def __init__(
        self,
        runtime: GatewayRuntime,
        *,
        default_agent_id: str = "main",
        session_prefix: str = "acp",
        event_writer: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._runtime = runtime
        self._default_agent_id = default_agent_id
        self._session_prefix = session_prefix
        self._event_writer = event_writer
        self._sessions: dict[str, ACPBridgeSession] = {}
        self._runs: dict[str, ACPRun] = {}

    async def handle_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = payload.get("id")
        method = str(payload.get("method") or payload.get("action") or "").strip()
        params = payload.get("params") or {}
        if not isinstance(params, dict):
            return self._response(request_id, ok=False, error="params must be an object")

        handler = getattr(self, f"_handle_{method}", None)
        if handler is None:
            return self._response(request_id, ok=False, error=f"unsupported method: {method}")

        try:
            result = await handler(params)
            return self._response(request_id, ok=True, result=result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            return self._response(request_id, ok=False, error=str(exc))

    async def run_stdio(self, input_stream: TextIO, output_stream: TextIO) -> int:
        self._event_writer = lambda item: self._write_json(output_stream, item)
        while True:
            line = await asyncio.to_thread(input_stream.readline)
            if not line:
                break
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                self._write_json(output_stream, self._response(None, ok=False, error=f"invalid json: {exc}"))
                continue

            if not isinstance(payload, dict):
                self._write_json(output_stream, self._response(None, ok=False, error="request must be an object"))
                continue

            response = await self.handle_request(payload)
            self._write_json(output_stream, response)

        await self.wait_for_runs()
        return 0

    async def wait_for_runs(self) -> None:
        if not self._runs:
            return
        await asyncio.gather(*(run.task for run in list(self._runs.values())), return_exceptions=True)

    async def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(params.get("agentId") or self._default_agent_id)
        self._default_agent_id = agent_id
        return {
            "protocol": "openlong-acp",
            "version": "0.1",
            "agentId": agent_id,
            "capabilities": ["prompt", "cancel", "listSessions", "reset"],
        }

    async def _handle_newSession(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = str(params.get("sessionId") or f"session-{uuid4().hex[:8]}")
        agent_id = str(params.get("agentId") or self._default_agent_id)
        gateway_session_id = str(params.get("sessionKey") or f"{self._session_prefix}:{uuid4().hex}")
        return self._ensure_session(session_id=session_id, gateway_session_id=gateway_session_id, agent_id=agent_id)

    async def _handle_listSessions(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        items: list[dict[str, Any]] = []
        for session in self._sessions.values():
            snapshot = self._runtime.session_manager.get_session_snapshot(session.gateway_session_id) or {}
            items.append({
                **session.to_dict(),
                "status": snapshot.get("status", "missing"),
                "messageCount": snapshot.get("message_count", 0),
            })
        items.sort(key=lambda item: item["updatedAt"], reverse=True)
        return {"sessions": items}

    async def _handle_prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = str(params.get("sessionId") or "").strip()
        if not session_id:
            raise ValueError("sessionId is required")

        text = str(params.get("text") or params.get("message") or "").strip()
        if not text:
            raise ValueError("text is required")

        agent_id = str(params.get("agentId") or self._default_agent_id)
        session = self._sessions.get(session_id)
        if session is None:
            gateway_session_id = str(params.get("sessionKey") or f"{self._session_prefix}:{uuid4().hex}")
            session_payload = self._ensure_session(session_id=session_id, gateway_session_id=gateway_session_id, agent_id=agent_id)
            session = self._sessions[session_id]
        else:
            if agent_id and session.agent_id != agent_id:
                self._runtime.assign_agent_to_session(session.gateway_session_id, agent_id)
                session.agent_id = agent_id
            session_payload = session.to_dict()

        run_id = str(params.get("runId") or f"run-{uuid4().hex[:12]}")
        task = asyncio.create_task(self._execute_prompt(run_id=run_id, session=session, text=text), name=f"acp-run-{run_id}")
        self._runs[run_id] = ACPRun(
            run_id=run_id,
            session_id=session.session_id,
            gateway_session_id=session.gateway_session_id,
            agent_id=session.agent_id,
            task=task,
        )
        return {
            "status": "accepted",
            "runId": run_id,
            **session_payload,
        }

    async def _handle_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        run_id = str(params.get("runId") or "").strip()
        if not run_id:
            raise ValueError("runId is required")
        run = self._runs.get(run_id)
        if run is None:
            return {"status": "not_found", "runId": run_id}
        if run.task.done():
            return {"status": "finished", "runId": run_id}
        self._write_event(
            {
                "type": "event",
                "event": "prompt.cancelled",
                "runId": run_id,
                "sessionId": run.session_id,
                "gatewaySessionId": run.gateway_session_id,
                "payload": {"status": "cancelled"},
            }
        )
        self._runs.pop(run_id, None)
        run.task.cancel()
        return {"status": "cancel_requested", "runId": run_id}

    async def _handle_reset(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = str(params.get("sessionId") or "").strip()
        if not session_id:
            raise ValueError("sessionId is required")
        session = self._sessions.pop(session_id, None)
        if session is not None:
            self._runtime.close_session(session.gateway_session_id, reason="acp_reset")
        agent_id = str(params.get("agentId") or (session.agent_id if session else self._default_agent_id))
        gateway_session_id = str(params.get("sessionKey") or f"{self._session_prefix}:{uuid4().hex}")
        payload = self._ensure_session(session_id=session_id, gateway_session_id=gateway_session_id, agent_id=agent_id)
        return {"status": "reset", **payload}

    def _ensure_session(self, *, session_id: str, gateway_session_id: str, agent_id: str) -> dict[str, Any]:
        snapshot = self._runtime.create_session(session_id=gateway_session_id, preferred_agent_id=agent_id)
        bridge_session = ACPBridgeSession(
            session_id=session_id,
            gateway_session_id=snapshot["session_id"],
            agent_id=snapshot["agent_id"],
            created_at=snapshot["created_at"],
            updated_at=snapshot["updated_at"],
        )
        self._sessions[session_id] = bridge_session
        return bridge_session.to_dict()

    async def _execute_prompt(self, *, run_id: str, session: ACPBridgeSession, text: str) -> None:
        try:
            result = await self._runtime.handle_user_message(
                session_id=session.gateway_session_id,
                user_message=text,
                preferred_agent_id=session.agent_id,
                source="acp",
            )
            snapshot = self._runtime.session_manager.get_session_snapshot(session.gateway_session_id) or {}
            session.updated_at = snapshot.get("updated_at", session.updated_at)
            self._write_event(
                {
                    "type": "event",
                    "event": "prompt.result",
                    "runId": run_id,
                    "sessionId": session.session_id,
                    "gatewaySessionId": session.gateway_session_id,
                    "payload": {"status": "ok", **result},
                }
            )
        except asyncio.CancelledError:
            if run_id in self._runs:
                self._write_event(
                    {
                        "type": "event",
                        "event": "prompt.cancelled",
                        "runId": run_id,
                        "sessionId": session.session_id,
                        "gatewaySessionId": session.gateway_session_id,
                        "payload": {"status": "cancelled"},
                    }
                )
            raise
        except Exception as exc:  # noqa: BLE001
            self._write_event(
                {
                    "type": "event",
                    "event": "prompt.result",
                    "runId": run_id,
                    "sessionId": session.session_id,
                    "gatewaySessionId": session.gateway_session_id,
                    "payload": {"status": "error", "error": str(exc)},
                }
            )
        finally:
            self._runs.pop(run_id, None)

    def _write_event(self, payload: dict[str, Any]) -> None:
        if self._event_writer is not None:
            self._event_writer(payload)

    def _response(self, request_id: Any, *, ok: bool, result: Any = None, error: str | None = None) -> dict[str, Any]:
        payload = {"id": request_id, "ok": ok}
        if ok:
            payload["result"] = result
        else:
            payload["error"] = error or "unknown error"
        return payload

    def _write_json(self, output_stream: TextIO, payload: dict[str, Any]) -> None:
        output_stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        output_stream.flush()
