from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.automation.cron import next_cron_time
from app.main import create_app


def test_cron_parser_next_run_supports_step_and_exact() -> None:
    base = datetime(2026, 3, 7, 10, 3, tzinfo=timezone.utc)
    assert next_cron_time("*/5 * * * *", after=base) == datetime(2026, 3, 7, 10, 5, tzinfo=timezone.utc)
    assert next_cron_time("15 11 * * *", after=base) == datetime(2026, 3, 7, 11, 15, tzinfo=timezone.utc)


def test_automation_api_flow_and_run_status(monkeypatch, tmp_path) -> None:
    from app.core.config import load_settings

    load_settings.cache_clear()
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("OPENLONG_DISABLE_MODEL_API", "1")

    client = TestClient(create_app())

    create_resp = client.post(
        "/automations",
        json={
            "name": "daily-summary",
            "agent_id": "main",
            "prompt": "请生成日报摘要",
            "cron": "*/5 * * * *",
            "enabled": True,
            "session_target": "isolated",
            "delivery_mode": "none",
        },
    )
    assert create_resp.status_code == 200
    job = create_resp.json()
    assert job["name"] == "daily-summary"
    assert job["next_run_at"]

    list_resp = client.get("/automations")
    assert list_resp.status_code == 200
    assert any(item["job_id"] == job["job_id"] for item in list_resp.json()["items"])

    update_resp = client.put(
        f"/automations/{job['job_id']}",
        json={
            "name": "daily-summary-updated",
            "agent_id": "main",
            "prompt": "请生成更新后的日报摘要",
            "cron": "*/10 * * * *",
            "enabled": True,
            "session_target": "isolated",
            "delivery_mode": "none",
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "daily-summary-updated"

    run_resp = client.post(f"/automations/{job['job_id']}/run")
    assert run_resp.status_code == 200
    run_payload = run_resp.json()
    assert run_payload["status"] == "success"
    assert run_payload["session_id"].startswith(f"cron:{job['job_id']}:")

    runs_resp = client.get("/automations/runs", params={"job_id": job["job_id"]})
    assert runs_resp.status_code == 200
    runs_payload = runs_resp.json()
    assert runs_payload["items"]
    assert runs_payload["items"][0]["job_id"] == job["job_id"]

    logs_resp = client.get("/logs", params={"event_name": "automation.run.completed", "limit": 10})
    assert logs_resp.status_code == 200
    assert any(item["payload"]["job_id"] == job["job_id"] for item in logs_resp.json()["items"])

    delete_resp = client.delete(f"/automations/{job['job_id']}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True


def test_automation_webhook_delivery_and_due_runner(monkeypatch, tmp_path) -> None:
    from app.core.config import load_settings

    load_settings.cache_clear()
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path / "workspace"))
    monkeypatch.setenv("OPENLONG_DISABLE_MODEL_API", "1")

    app = create_app()
    delivered: list[dict] = []

    async def fake_webhook(job, run):
        delivered.append({"job_id": job.job_id, "run_id": run.run_id, "target": job.delivery_to})
        return {"status_code": 202, "delivered_to": job.delivery_to}

    monkeypatch.setattr(app.state.runtime.automation_service, "_deliver_webhook", fake_webhook)

    client = TestClient(app)
    create_resp = client.post(
        "/automations",
        json={
            "name": "webhook-job",
            "agent_id": "main",
            "prompt": "请做巡检摘要",
            "cron": "* * * * *",
            "enabled": True,
            "session_target": "isolated",
            "delivery_mode": "webhook",
            "delivery_to": "https://example.com/hook",
        },
    )
    job = create_resp.json()

    # force due and run through due-runner API
    app.state.runtime.automation_service.manager.update_job(job["job_id"], cron="* * * * *")
    forced = app.state.runtime.automation_service.manager.get_job(job["job_id"])
    forced.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    app.state.runtime.automation_service.manager._save_jobs()  # noqa: SLF001

    due_resp = client.post("/automations/run-due")
    assert due_resp.status_code == 200
    due_runs = due_resp.json()
    assert due_runs
    assert due_runs[0]["job_id"] == job["job_id"]
    assert delivered
    assert delivered[0]["target"] == "https://example.com/hook"

