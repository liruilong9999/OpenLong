from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from app.automation.cron import next_cron_time
from app.automation.types import AutomationDeliveryMode, AutomationJob, AutomationRun, AutomationRunStatus, AutomationSessionTarget


class AutomationManager:
    def __init__(self, storage_root: str | Path) -> None:
        self._storage_root = Path(storage_root).resolve()
        self._jobs_path = self._storage_root / "jobs.json"
        self._runs_dir = self._storage_root / "runs"
        self._lock = Lock()
        self._storage_root.mkdir(parents=True, exist_ok=True)
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, AutomationJob] = self._load_jobs()

    def list_jobs(self) -> list[AutomationJob]:
        with self._lock:
            items = list(self._jobs.values())
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items

    def get_job(self, job_id: str) -> AutomationJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def create_job(
        self,
        *,
        name: str,
        agent_id: str,
        prompt: str,
        cron: str,
        enabled: bool = True,
        session_target: str = "isolated",
        delivery_mode: str = "none",
        delivery_to: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> AutomationJob:
        job = AutomationJob(
            job_id=str(uuid4()),
            name=name.strip() or "unnamed-job",
            agent_id=agent_id.strip() or "main",
            prompt=prompt.strip(),
            cron=cron.strip(),
            enabled=enabled,
            session_target=AutomationSessionTarget(session_target),
            delivery_mode=AutomationDeliveryMode(delivery_mode),
            delivery_to=delivery_to.strip(),
            metadata=dict(metadata or {}),
        )
        job.next_run_at = next_cron_time(job.cron)
        self._validate_job(job)
        with self._lock:
            self._jobs[job.job_id] = job
            self._save_jobs()
        return job

    def update_job(self, job_id: str, **changes: Any) -> AutomationJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise FileNotFoundError(job_id)

            if "name" in changes:
                job.name = str(changes["name"] or job.name).strip() or job.name
            if "agent_id" in changes:
                job.agent_id = str(changes["agent_id"] or job.agent_id).strip() or job.agent_id
            if "prompt" in changes:
                job.prompt = str(changes["prompt"] or job.prompt).strip()
            if "cron" in changes:
                job.cron = str(changes["cron"] or job.cron).strip()
            if "enabled" in changes:
                job.enabled = bool(changes["enabled"])
            if "session_target" in changes:
                job.session_target = AutomationSessionTarget(str(changes["session_target"] or job.session_target.value))
            if "delivery_mode" in changes:
                job.delivery_mode = AutomationDeliveryMode(str(changes["delivery_mode"] or job.delivery_mode.value))
            if "delivery_to" in changes:
                job.delivery_to = str(changes["delivery_to"] or "").strip()
            if "metadata" in changes and isinstance(changes["metadata"], dict):
                job.metadata = dict(changes["metadata"])

            job.updated_at = datetime.now(timezone.utc)
            job.next_run_at = next_cron_time(job.cron, after=job.last_run_at or job.updated_at)
            self._validate_job(job)
            self._save_jobs()
            return job

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            deleted = self._jobs.pop(job_id, None)
            self._save_jobs()
        return deleted is not None

    def due_jobs(self, *, now) -> list[AutomationJob]:
        with self._lock:
            jobs = [item for item in self._jobs.values() if item.enabled and item.next_run_at and item.next_run_at <= now]
        jobs.sort(key=lambda item: item.next_run_at or now)
        return jobs

    def mark_job_scheduled(self, job_id: str, *, when) -> AutomationJob:
        with self._lock:
            job = self._jobs[job_id]
            job.last_run_at = when
            job.updated_at = when
            job.next_run_at = next_cron_time(job.cron, after=when)
            self._save_jobs()
            return job

    def create_run(self, *, job: AutomationJob, session_id: str) -> AutomationRun:
        run = AutomationRun(
            run_id=str(uuid4()),
            job_id=job.job_id,
            agent_id=job.agent_id,
            session_id=session_id,
            delivery_mode=job.delivery_mode,
            delivery_to=job.delivery_to,
        )
        self._save_run(run)
        return run

    def update_run(self, run: AutomationRun) -> None:
        self._save_run(run)

    def list_runs(self, *, job_id: str | None = None, limit: int = 100) -> list[AutomationRun]:
        items: list[AutomationRun] = []
        for path in sorted(self._runs_dir.glob("*.json"), key=lambda item: item.name, reverse=True):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                run = AutomationRun.from_dict(payload)
            except Exception:
                continue
            if job_id and run.job_id != job_id:
                continue
            items.append(run)
            if len(items) >= limit:
                break
        return items

    def stats(self) -> dict[str, int]:
        jobs = self.list_jobs()
        runs = self.list_runs(limit=1000)
        return {
            "jobs": len(jobs),
            "enabled_jobs": sum(1 for item in jobs if item.enabled),
            "runs": len(runs),
            "running_runs": sum(1 for item in runs if item.status == AutomationRunStatus.RUNNING),
            "failed_runs": sum(1 for item in runs if item.status == AutomationRunStatus.FAILED),
        }

    def _load_jobs(self) -> dict[str, AutomationJob]:
        if not self._jobs_path.exists():
            return {}
        try:
            payload = json.loads(self._jobs_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        items = payload if isinstance(payload, list) else []
        jobs = [AutomationJob.from_dict(item) for item in items if isinstance(item, dict)]
        return {item.job_id: item for item in jobs}

    def _save_jobs(self) -> None:
        items = [item.to_dict() for item in self._jobs.values()]
        self._jobs_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    def _save_run(self, run: AutomationRun) -> None:
        path = self._runs_dir / f"{run.run_id}.json"
        path.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _validate_job(self, job: AutomationJob) -> None:
        if not job.prompt:
            raise ValueError("automation prompt cannot be empty")
        if not job.cron:
            raise ValueError("automation cron cannot be empty")
        if job.delivery_mode == AutomationDeliveryMode.WEBHOOK and not job.delivery_to:
            raise ValueError("webhook delivery requires delivery_to")
