from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.workspace.manager import WorkspaceManager


def test_context_priority_cache_and_dynamic_update(tmp_path: Path) -> None:
    workspace_manager = WorkspaceManager(str(tmp_path))
    agent_id = "agent-a"

    first = workspace_manager.get_context_snapshot(agent_id)
    assert first["cache_hit"] is False
    assert first["priority_order"] == ["RULES.md", "IDENTITY.md", "SOUL.md", "STYLE.md", "USER.md"]

    second = workspace_manager.get_context_snapshot(agent_id)
    assert second["cache_hit"] is True

    updated_user = workspace_manager.update_context(
        agent_id=agent_id,
        context_name="USER",
        content="用户名：Alice\n偏好：简洁",
        dynamic_only=True,
    )
    assert "Alice" in updated_user["files"]["USER.md"]["body"]

    updated_style = workspace_manager.update_context(
        agent_id=agent_id,
        context_name="STYLE.md",
        content="请使用中文并尽量简短。",
        dynamic_only=True,
    )
    assert "尽量简短" in updated_style["files"]["STYLE.md"]["body"]

    prompt_block = updated_style["prompt_block"]
    assert prompt_block.index("## RULES.md") < prompt_block.index("## IDENTITY.md")
    assert prompt_block.index("## IDENTITY.md") < prompt_block.index("## SOUL.md")
    assert prompt_block.index("## SOUL.md") < prompt_block.index("## STYLE.md")
    assert prompt_block.index("## STYLE.md") < prompt_block.index("## USER.md")

    with pytest.raises(PermissionError):
        workspace_manager.update_context(
            agent_id=agent_id,
            context_name="RULES",
            content="禁止修改",
            dynamic_only=True,
        )


def test_context_workspace_isolation(tmp_path: Path) -> None:
    workspace_manager = WorkspaceManager(str(tmp_path))

    workspace_manager.update_context("agent-a", "USER", "A-user", dynamic_only=True)
    workspace_manager.update_context("agent-b", "USER", "B-user", dynamic_only=True)

    context_a = workspace_manager.get_context_snapshot("agent-a")
    context_b = workspace_manager.get_context_snapshot("agent-b")

    assert "A-user" in context_a["files"]["USER.md"]["body"]
    assert "B-user" in context_b["files"]["USER.md"]["body"]
    assert context_a["workspace_path"] != context_b["workspace_path"]


def test_context_api_update_and_reload() -> None:
    client = TestClient(create_app())

    base_context = client.get("/agents/main/context")
    assert base_context.status_code == 200
    base_payload = base_context.json()
    assert base_payload["priority_order"][0] == "RULES.md"

    update_user = client.put(
        "/agents/main/context/USER",
        json={"content": "昵称：测试用户"},
    )
    assert update_user.status_code == 200
    assert "测试用户" in update_user.json()["files"]["USER.md"]["body"]

    update_style = client.put(
        "/agents/main/context/STYLE",
        json={"content": "回答风格：先结论后细节"},
    )
    assert update_style.status_code == 200
    assert "先结论" in update_style.json()["files"]["STYLE.md"]["body"]

    reload_resp = client.post("/agents/main/context/reload")
    assert reload_resp.status_code == 200
    assert reload_resp.json()["cache_hit"] is False

    blocked = client.put(
        "/agents/main/context/RULES",
        json={"content": "尝试覆盖规则"},
    )
    assert blocked.status_code == 400
