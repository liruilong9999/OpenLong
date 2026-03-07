from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.plugins.manager import PluginManager
from app.skills.loader import SkillLoader
from app.workspace.manager import WorkspaceManager
from app.main import create_app


PLUGIN_SKILL_MD = """# RepoPluginSkill

## 技能说明
用于读取仓库说明文档。

## 触发条件
- 插件
- readme

## 参数说明
- path(path,required): 文件路径

## 示例
- 用户说：读取 README.md
"""


def test_plugin_manager_install_enable_disable_and_delete(tmp_path: Path) -> None:
    workspace_manager = WorkspaceManager(str(tmp_path))
    plugin_manager = PluginManager(workspace_manager)
    loader = SkillLoader(workspace_manager, plugin_manager=plugin_manager)

    plugin = loader.install_plugin(
        agent_id="main",
        plugin_id="repo_helper",
        manifest={
            "id": "repo_helper",
            "name": "Repo Helper",
            "description": "Plugin-backed repo helper.",
            "version": "0.1.0",
            "enabled": True,
            "config_schema": {
                "type": "object",
                "properties": {"workspace_mode": {"type": "string", "enum": ["readonly", "full"]}},
                "required": ["workspace_mode"],
            },
            "config": {"workspace_mode": "readonly"},
            "skills": ["skills"],
            "default_tools": ["file"],
            "optional_tools": ["shell"],
        },
        skills={"repo_skill": PLUGIN_SKILL_MD},
    )

    assert plugin["plugin_id"] == "repo_helper"
    assert plugin["enabled"] is True

    snapshot = loader.snapshot("main")
    assert snapshot["plugins"]["count"] == 1
    assert any(item["plugin_id"] == "repo_helper" for item in snapshot["plugins"]["plugins"])
    plugin_skill = next(item for item in snapshot["skills"] if item["plugin_id"] == "repo_helper")
    assert plugin_skill["default_tools"] == ["file"]
    assert plugin_skill["optional_tools"] == ["shell"]

    disabled = loader.set_plugin_enabled("main", "repo_helper", False)
    assert disabled["enabled"] is False
    disabled_snapshot = loader.snapshot("main", force_refresh=True)
    assert not any(item["plugin_id"] == "repo_helper" for item in disabled_snapshot["skills"])

    enabled = loader.set_plugin_enabled("main", "repo_helper", True)
    assert enabled["enabled"] is True
    enabled_snapshot = loader.snapshot("main", force_refresh=True)
    assert any(item["plugin_id"] == "repo_helper" for item in enabled_snapshot["skills"])

    deleted = loader.delete_plugin("main", "repo_helper")
    assert deleted is True
    deleted_snapshot = loader.snapshot("main", force_refresh=True)
    assert deleted_snapshot["plugins"]["count"] == 0


def test_plugin_manager_rejects_invalid_config_schema(tmp_path: Path) -> None:
    workspace_manager = WorkspaceManager(str(tmp_path))
    plugin_manager = PluginManager(workspace_manager)
    loader = SkillLoader(workspace_manager, plugin_manager=plugin_manager)

    with pytest.raises(ValueError, match="missing required field"):
        loader.install_plugin(
            agent_id="main",
            plugin_id="broken_plugin",
            manifest={
                "id": "broken_plugin",
                "name": "Broken Plugin",
                "description": "broken",
                "version": "0.1.0",
                "config_schema": {
                    "type": "object",
                    "properties": {"token": {"type": "string"}},
                    "required": ["token"],
                },
                "config": {},
                "skills": ["skills"],
            },
            skills={"broken_skill": PLUGIN_SKILL_MD},
        )


def test_plugin_api_endpoints() -> None:
    client = TestClient(create_app())

    template_resp = client.get("/agents/main/plugins/template", params={"plugin_id": "repo_helper"})
    assert template_resp.status_code == 200
    assert template_resp.json()["template"]["id"] == "repo_helper"

    upsert_resp = client.put(
        "/agents/main/plugins/repo_helper",
        json={
            "manifest": {
                "id": "repo_helper",
                "name": "Repo Helper",
                "description": "Plugin-backed repo helper.",
                "version": "0.1.0",
                "enabled": True,
                "config_schema": {"type": "object", "properties": {}, "required": []},
                "config": {},
                "skills": ["skills"],
                "default_tools": ["file"],
                "optional_tools": ["shell"],
            },
            "skills": {"repo_skill": PLUGIN_SKILL_MD},
        },
    )
    assert upsert_resp.status_code == 200
    assert upsert_resp.json()["plugin_id"] == "repo_helper"

    list_resp = client.get("/agents/main/plugins")
    assert list_resp.status_code == 200
    assert list_resp.json()["count"] >= 1

    disable_resp = client.post("/agents/main/plugins/repo_helper/state", json={"enabled": False})
    assert disable_resp.status_code == 200
    assert disable_resp.json()["enabled"] is False

    reload_resp = client.post("/agents/main/plugins/reload")
    assert reload_resp.status_code == 200
    assert reload_resp.json()["count"] >= 1

    delete_resp = client.delete("/agents/main/plugins/repo_helper")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True
