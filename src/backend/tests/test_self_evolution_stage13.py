from app.main import create_app
from app.self_evolution.engine import SelfEvolutionEngine


def test_self_evolution_engine_generates_findings_and_suggestions() -> None:
    engine = SelfEvolutionEngine()
    snapshot = {
        "readiness": {"status": "not_ready", "checks": {"config_valid": False}},
        "task_queue": {"total": 12, "failed": 2},
        "tool_logs": {"total": 10, "failed": 3, "denied": 2},
        "recent_tool_logs": [
            {"tool_name": "shell", "success": False, "denied_reason": "approval pending"},
            {"tool_name": "file", "success": False, "denied_reason": None},
        ],
        "model_router": {"total": 6, "failed": 1, "fallback_activations": 2},
        "recent_model_calls": [{"success": False, "model": "gpt-x"}],
        "automations": {"stats": {"jobs": 2, "failed_runs": 1}},
        "automation_runs": [{"status": "failed", "job_id": "job-1"}],
        "recent_events": [{"name": "task.failed"}],
        "warnings": ["unsafe bind"],
        "errors": ["missing token"],
    }

    report = engine.evaluate("main", snapshot)
    payload = report.to_dict()

    assert payload["findings"]
    assert payload["suggestions"]
    assert payload["update_plan"]
    assert any(item["kind"] == "readiness" for item in payload["findings"])
    assert any(item["priority"] == "P0" for item in payload["suggestions"])


def test_doctor_and_self_evolution_endpoint_include_report() -> None:
    client = create_app()
    from fastapi.testclient import TestClient

    test_client = TestClient(client)

    doctor_resp = test_client.get("/doctor")
    assert doctor_resp.status_code in {200, 503}
    doctor_payload = doctor_resp.json()
    assert "self_evolution" in doctor_payload
    assert "suggestions" in doctor_payload["self_evolution"]

    evolution_resp = test_client.get("/self-evolution", params={"agent_id": "main"})
    assert evolution_resp.status_code == 200
    evolution_payload = evolution_resp.json()
    assert evolution_payload["agent_id"] == "main"
    assert "findings" in evolution_payload
    assert "suggestions" in evolution_payload
