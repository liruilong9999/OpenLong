from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any


class TaskQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[Callable[[], Awaitable[Any]]] = asyncio.Queue()

    async def submit(self, task_factory: Callable[[], Awaitable[Any]]) -> None:
        await self._queue.put(task_factory)

    async def run_once(self) -> Any:
        task_factory = await self._queue.get()
        try:
            return await task_factory()
        finally:
            self._queue.task_done()
