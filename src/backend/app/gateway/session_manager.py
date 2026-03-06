from __future__ import annotations

from threading import Lock

from app.models.message import ChatMessage
from app.models.session import SessionRecord


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}
        self._lock = Lock()

    def get_or_create(self, session_id: str, agent_id: str = "main") -> SessionRecord:
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None:
                record = SessionRecord(session_id=session_id, agent_id=agent_id)
                self._sessions[session_id] = record
            return record

    def append_message(self, session_id: str, message: ChatMessage) -> None:
        with self._lock:
            session = self._sessions[session_id]
            session.messages.append(message)

    def list_sessions(self) -> list[dict[str, str | int]]:
        with self._lock:
            return [
                {
                    "session_id": session.session_id,
                    "agent_id": session.agent_id,
                    "message_count": len(session.messages),
                }
                for session in self._sessions.values()
            ]
