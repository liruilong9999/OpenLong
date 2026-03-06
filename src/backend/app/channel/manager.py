from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ChannelAdapter(Protocol):
    name: str

    async def send(self, session_id: str, message: str) -> None:
        ...


@dataclass(slots=True)
class ChannelManager:
    adapters: dict[str, ChannelAdapter] | None = None

    def __post_init__(self) -> None:
        if self.adapters is None:
            self.adapters = {}

    def register(self, adapter: ChannelAdapter) -> None:
        self.adapters[adapter.name] = adapter

    def list_channels(self) -> list[str]:
        return sorted(self.adapters.keys())

    async def send(self, channel: str, session_id: str, message: str) -> bool:
        adapter = self.adapters.get(channel)
        if adapter is None:
            return False
        await adapter.send(session_id=session_id, message=message)
        return True
