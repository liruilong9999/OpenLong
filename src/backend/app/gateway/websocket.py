from __future__ import annotations

from collections import defaultdict

from fastapi import WebSocket


class WebSocketHub:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[session_id].add(websocket)

    def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        self._connections[session_id].discard(websocket)

    async def broadcast(self, session_id: str, payload: dict) -> None:
        for ws in self._connections.get(session_id, set()):
            await ws.send_json(payload)
