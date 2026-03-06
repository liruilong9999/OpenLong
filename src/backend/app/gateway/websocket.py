from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Any

from fastapi import WebSocket


class WebSocketHub:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = Lock()

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        with self._lock:
            self._connections[session_id].add(websocket)

    def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        with self._lock:
            session_conns = self._connections.get(session_id)
            if not session_conns:
                return

            session_conns.discard(websocket)
            if not session_conns:
                self._connections.pop(session_id, None)

    async def broadcast(self, session_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            sockets = list(self._connections.get(session_id, set()))

        stale: list[WebSocket] = []
        for ws in sockets:
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)

        if stale:
            with self._lock:
                session_conns = self._connections.get(session_id, set())
                for ws in stale:
                    session_conns.discard(ws)

    def broadcast_nowait(self, session_id: str, payload: dict[str, Any]) -> None:
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast(session_id=session_id, payload=payload))
        except RuntimeError:
            return

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            active_sessions = len(self._connections)
            active_connections = sum(len(items) for items in self._connections.values())

        return {
            "active_sessions": active_sessions,
            "active_connections": active_connections,
        }
