from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class Event:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[Event], None]]] = defaultdict(list)

    def subscribe(self, event_name: str, handler: Callable[[Event], None]) -> None:
        self._handlers[event_name].append(handler)

    def publish(self, event: Event) -> None:
        for handler in self._handlers.get(event.name, []):
            handler(event)
