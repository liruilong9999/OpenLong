from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from time import perf_counter
from typing import Any
from uuid import uuid4

from app.core.events import EventBus


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskKind(str, Enum):
    AGENT = "agent"
    TOOL = "tool"
    MEMORY = "memory"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    kind: TaskKind
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=_utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    latency_ms: float | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "kind": self.kind.value,
            "name": self.name,
            "status": self.status.value,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass(slots=True)
class _TaskEnvelope:
    record: TaskRecord
    task_factory: Any
    future: asyncio.Future[Any]


class TaskQueue:
    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._queue: asyncio.Queue[_TaskEnvelope] = asyncio.Queue()
        self._records: dict[str, TaskRecord] = {}
        self._futures: dict[str, asyncio.Future[Any]] = {}
        self._worker_task: asyncio.Task[None] | None = None
        self._event_bus = event_bus

    def _emit(self, name: str, payload: dict[str, Any]) -> None:
        if self._event_bus is not None:
            self._event_bus.emit(name, payload)

    def _ensure_worker(self) -> None:
        if self._worker_task is not None and not self._worker_task.done():
            return

        self._worker_task = asyncio.create_task(self._worker_loop(), name="gateway-task-worker")

    async def submit(
        self,
        kind: TaskKind,
        name: str,
        payload: dict[str, Any],
        task_factory: Any,
    ) -> str:
        loop = asyncio.get_running_loop()
        task_id = str(uuid4())
        record = TaskRecord(task_id=task_id, kind=kind, name=name, payload=payload)
        future: asyncio.Future[Any] = loop.create_future()

        self._records[task_id] = record
        self._futures[task_id] = future
        await self._queue.put(_TaskEnvelope(record=record, task_factory=task_factory, future=future))
        self._ensure_worker()

        self._emit(
            "task.submitted",
            {
                "task_id": task_id,
                "kind": kind.value,
                "name": name,
            },
        )
        return task_id

    async def wait(self, task_id: str, timeout: float | None = None) -> Any:
        future = self._futures[task_id]
        if timeout is None:
            return await future
        return await asyncio.wait_for(future, timeout=timeout)

    async def submit_and_wait(
        self,
        kind: TaskKind,
        name: str,
        payload: dict[str, Any],
        task_factory: Any,
        timeout: float | None = None,
    ) -> tuple[str, Any]:
        task_id = await self.submit(kind=kind, name=name, payload=payload, task_factory=task_factory)
        result = await self.wait(task_id, timeout=timeout)
        return task_id, result

    async def _worker_loop(self) -> None:
        while True:
            envelope = await self._queue.get()
            record = envelope.record
            started = perf_counter()
            record.status = TaskStatus.RUNNING
            record.started_at = _utc_now()

            self._emit(
                "task.started",
                {
                    "task_id": record.task_id,
                    "kind": record.kind.value,
                    "name": record.name,
                },
            )

            try:
                result = await envelope.task_factory()
                record.status = TaskStatus.SUCCESS
                if not envelope.future.done():
                    envelope.future.set_result(result)

                self._emit(
                    "task.completed",
                    {
                        "task_id": record.task_id,
                        "kind": record.kind.value,
                        "name": record.name,
                    },
                )
            except Exception as exc:
                record.status = TaskStatus.FAILED
                record.error = str(exc)
                if not envelope.future.done():
                    envelope.future.set_exception(exc)

                self._emit(
                    "task.failed",
                    {
                        "task_id": record.task_id,
                        "kind": record.kind.value,
                        "name": record.name,
                        "error": str(exc),
                    },
                )
            finally:
                record.finished_at = _utc_now()
                record.latency_ms = round((perf_counter() - started) * 1000, 3)
                self._queue.task_done()

    def list_tasks(self, limit: int = 100, kind: TaskKind | None = None) -> list[dict[str, Any]]:
        records = list(self._records.values())
        if kind is not None:
            records = [item for item in records if item.kind == kind]

        records.sort(key=lambda item: item.created_at, reverse=True)
        return [item.to_dict() for item in records[:limit]]

    def stats(self) -> dict[str, int]:
        records = list(self._records.values())
        return {
            "total": len(records),
            "pending": sum(1 for item in records if item.status == TaskStatus.PENDING),
            "running": sum(1 for item in records if item.status == TaskStatus.RUNNING),
            "success": sum(1 for item in records if item.status == TaskStatus.SUCCESS),
            "failed": sum(1 for item in records if item.status == TaskStatus.FAILED),
            "queue_size": self._queue.qsize(),
        }
