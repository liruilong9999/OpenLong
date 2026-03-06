from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import logging
from threading import Lock
from typing import Any, Callable
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class Event:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


class EventBus:
    def __init__(self, history_limit: int = 2000) -> None:
        self._handlers: dict[str, list[Callable[[Event], None]]] = defaultdict(list)
        self._history: deque[Event] = deque(maxlen=history_limit)
        self._lock = Lock()

    def subscribe(self, event_name: str, handler: Callable[[Event], None]) -> None:
        with self._lock:
            self._handlers[event_name].append(handler)

    def unsubscribe(self, event_name: str, handler: Callable[[Event], None]) -> None:
        with self._lock:
            handlers = self._handlers.get(event_name, [])
            if handler in handlers:
                handlers.remove(handler)

    def publish(self, event: Event) -> None:
        with self._lock:
            self._history.append(event)
            handlers = list(self._handlers.get(event.name, []))

        for handler in handlers:
            try:
                handler(event)
            except Exception:
                logging.getLogger(__name__).exception("Event handler failed: %s", event.name)

    def emit(self, name: str, payload: dict[str, Any] | None = None) -> Event:
        event = Event(name=name, payload=payload or {})
        self.publish(event)
        return event

    def recent(self, limit: int = 100, event_name: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if event_name:
                events = [item for item in self._history if item.name == event_name]
            else:
                events = list(self._history)

        return [event.to_dict() for event in events[-limit:]][::-1]
