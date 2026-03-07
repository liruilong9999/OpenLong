from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

import httpx

from app.automation.manager import AutomationManager
from app.automation.types import AutomationDeliveryMode, AutomationJob, AutomationRun, AutomationRunStatus, AutomationSessionTarget

if TYPE_CHECKING:
    from app.gateway.runtime import GatewayRuntime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AutomationService:
    def __init__(self, storage_root: str | Path, *, webhook_token: str = "", tick_seconds: float = 5.0) -> None:
        self._manager = AutomationManager(storage_root)
        self._webhook_token = webhook_token.strip()
        self._tick_seconds = max(tick_seconds, 1.0)
        self._runtime: GatewayRuntime | None = None
        self._loop_task: asyncio.Task[None] | None = None

    @property
    def manager(self) -> AutomationManager:
        return self._manager

    def bind_runtime(self, runtime: "GatewayRuntime") -> None:
        self._runtime = runtime

    async def start(self) -> None:
        if self._loop_task is not None and not self._loop_task.done():
            return
        self._loop_task = asyncio.create_task(self._loop(), name="automation-scheduler")

    async def stop(self) -> None:
        if self._loop_task is None:
            return
        self._loop_task.cancel()
        try:
            await self._loop_task
        except asyncio.CancelledError:
            pass
        self._loop_task = None

    def list_jobs(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self._manager.list_jobs()],
            "stats": self._manager.stats(),
        }

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        job = self._manager.get_job(job_id)
        return job.to_dict() if job is not None else None

    def create_job(self, **kwargs: Any) -> dict[str, Any]:
        return self._manager.create_job(**kwargs).to_dict()

    def update_job(self, job_id: str, **changes: Any) -> dict[str, Any]:
        return self._manager.update_job(job_id, **changes).to_dict()

    def delete_job(self, job_id: str) -> dict[str, Any]:
        return {"deleted": self._manager.delete_job(job_id), "job_id": job_id}

    def list_runs(self, *, job_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        runs = self._manager.list_runs(job_id=job_id, limit=limit)
        return {
            "items": [item.to_dict() for item in runs],
            "stats": self._manager.stats(),
        }

    async def run_job(self, job_id: str, *, now: datetime | None = None) -> dict[str, Any]:
        job = self._manager.get_job(job_id)
        if job is None:
            raise FileNotFoundError(job_id)
        return (await self._execute_job(job, now=now)).to_dict()

    async def run_due_jobs(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        moment = now or _utc_now()
        results: list[dict[str, Any]] = []
        for job in self._manager.due_jobs(now=moment):
            results.append((await self._execute_job(job, now=moment)).to_dict())
        return results

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_due_jobs()
            except asyncio.CancelledError:
                raise
            except Exception:
                if self._runtime is not None:
                    self._runtime.event_bus.emit(
                        "automation.loop.failed",
                        {"session_id": "", "agent_id": "main"},
                    )
            await asyncio.sleep(self._tick_seconds)

    async def _execute_job(self, job: AutomationJob, *, now: datetime | None = None) -> AutomationRun:
        if self._runtime is None:
            raise RuntimeError("automation service is not bound to a runtime")

        moment = now or _utc_now()
        session_id = self._session_id_for_job(job, now=moment)
        run = self._manager.create_run(job=job, session_id=session_id)
        run.status = AutomationRunStatus.RUNNING
        run.started_at = moment
        self._manager.update_run(run)

        self._runtime.event_bus.emit(
            "automation.run.started",
            {
                "session_id": session_id,
                "agent_id": job.agent_id,
                "job_id": job.job_id,
                "run_id": run.run_id,
            },
        )

        try:
            result = await self._runtime.handle_user_message(
                session_id=session_id,
                user_message=job.prompt,
                preferred_agent_id=job.agent_id,
                source="automation",
            )
            run.status = AutomationRunStatus.SUCCESS
            run.result = result
            run.finished_at = _utc_now()
            run.task_id = str(result.get("task_id") or "")

            if job.delivery_mode == AutomationDeliveryMode.WEBHOOK and job.delivery_to:
                delivery = await self._deliver_webhook(job, run)
                run.result = {**run.result, "webhook": delivery}

            self._runtime.event_bus.emit(
                "automation.run.completed",
                {
                    "session_id": session_id,
                    "agent_id": job.agent_id,
                    "job_id": job.job_id,
                    "run_id": run.run_id,
                    "success": True,
                },
            )
        except Exception as exc:  # noqa: BLE001
            run.status = AutomationRunStatus.FAILED
            run.error = str(exc)
            run.finished_at = _utc_now()
            self._runtime.event_bus.emit(
                "automation.run.failed",
                {
                    "session_id": session_id,
                    "agent_id": job.agent_id,
                    "job_id": job.job_id,
                    "run_id": run.run_id,
                    "error": str(exc),
                },
            )
        finally:
            self._manager.update_run(run)
            self._manager.mark_job_scheduled(job.job_id, when=moment)

        return run

    async def _deliver_webhook(self, job: AutomationJob, run: AutomationRun) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self._webhook_token:
            headers["Authorization"] = f"Bearer {self._webhook_token}"

        payload = {
            "job": job.to_dict(),
            "run": run.to_dict(),
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(job.delivery_to, headers=headers, json=payload)
            response.raise_for_status()
        return {"status_code": response.status_code, "delivered_to": job.delivery_to}

    def _session_id_for_job(self, job: AutomationJob, *, now: datetime) -> str:
        if job.session_target == AutomationSessionTarget.SHARED:
            return f"cron:{job.job_id}:shared"
        return f"cron:{job.job_id}:{int(now.timestamp())}"
