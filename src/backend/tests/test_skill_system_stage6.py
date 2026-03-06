from pathlib import Path

from fastapi.testclient import TestClient

from app.agent.prompt_builder import PromptBuilder
from app.memory.manager import MemoryManager
from app.models.message import ChatMessage, Role
from app.skills.loader import SkillLoader
from app.tools.builtins.file_tool import FileTool
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.workspace.manager import WorkspaceManager
from app.main import create_app


HTTP_SKILL_MD = """# HttpFetchSkill

## 技能说明
通过 HTTP 工具抓取网页文本。

## 触发条件
- http
- 网址
- api

## 参数说明
- url(url,required): 目标地址
- timeout(number,optional): 超时时间

## 示例
- 用户说：请抓取 https://example.com
- Agent 行为：匹配技能并调用 http 工具
"""


FILE_SKILL_MD = """# FileReadSkill

## 技能说明
读取工作区中的文件内容。

## 触发条件
- 文件
- read
- 路径

## 参数说明
- path(path,required): 文件相对路径

## 示例
- 用户说：读取 README.md
- Agent 行为：调用 file 工具 action=read
"""


def test_skill_loader_registry_match_and_dynamic_reload(tmp_path: Path) -> None:
    workspace_manager = WorkspaceManager(str(tmp_path))
    loader = SkillLoader(workspace_manager)

    http_skill = loader.upsert_skill_markdown("main", "http_fetch", HTTP_SKILL_MD)
    file_skill = loader.upsert_skill_markdown("main", "file_read", FILE_SKILL_MD)

    skills = loader.load("main")
    assert len(skills) == 2
    assert {item.skill_id for item in skills} == {"http_fetch", "file_read"}
    assert http_skill.triggers
    assert file_skill.parameters

    matches = loader.match_with_scores("main", "请访问一个网址并调用 http api", max_items=3)
    assert matches
    assert matches[0]["skill"]["skill_id"] == "http_fetch"

    # 动态新增 skill（无需重启）：直接写入后再次 load 即可被识别。
    workspace = workspace_manager.ensure_agent_workspace("main")
    new_skill_dir = workspace / "skills" / "shell_helper"
    new_skill_dir.mkdir(parents=True, exist_ok=True)
    (new_skill_dir / "SKILL.md").write_text(
        "# ShellHelper\n\n## 技能说明\n执行终端命令。\n\n## 触发条件\n- shell\n\n## 参数说明\n- input(string,required): 命令\n\n## 示例\n- /shell Get-Location\n",
        encoding="utf-8",
    )

    refreshed = loader.load("main")
    assert any(item.skill_id == "shell_helper" for item in refreshed)


def test_skill_prompt_injection(tmp_path: Path) -> None:
    workspace_manager = WorkspaceManager(str(tmp_path))
    loader = SkillLoader(workspace_manager)
    loader.upsert_skill_markdown("main", "http_fetch", HTTP_SKILL_MD)
    skills = loader.load("main")
    matched = loader.match("main", "请帮我请求一个 http api", max_items=2)

    prompt = PromptBuilder().build(
        context_block="RULES: obey constraints",
        history=[ChatMessage(role=Role.USER, content="你好")],
        memories=["[conversation] hello"],
        skills=skills,
        matched_skills=matched,
        user_message="请请求 https://example.com",
        scratchpad="",
    )

    assert "[MATCHED_SKILLS]" in prompt.full_prompt
    assert "HttpFetchSkill" in prompt.full_prompt
    assert "触发条件" not in prompt.full_prompt  # prompt_view 已转为结构化文本


def test_skill_api_endpoints() -> None:
    client = TestClient(create_app())

    template_resp = client.get("/agents/main/skills/template", params={"skill_name": "web_reader"})
    assert template_resp.status_code == 200
    assert "## 技能说明" in template_resp.json()["template"]

    upsert_resp = client.put(
        "/agents/main/skills/http_fetch",
        json={"markdown": HTTP_SKILL_MD},
    )
    assert upsert_resp.status_code == 200
    assert upsert_resp.json()["skill_id"] == "http_fetch"

    list_resp = client.get("/agents/main/skills")
    assert list_resp.status_code == 200
    assert list_resp.json()["count"] >= 1

    match_resp = client.get(
        "/agents/main/skills/match",
        params={"query": "请用 http 访问网址", "limit": 3},
    )
    assert match_resp.status_code == 200
    assert match_resp.json()["matches"]

    reload_resp = client.post("/agents/main/skills/reload")
    assert reload_resp.status_code == 200

    delete_resp = client.delete("/agents/main/skills/http_fetch")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True


def test_skill_loader_with_runtime_dependencies(tmp_path: Path) -> None:
    workspace_manager = WorkspaceManager(str(tmp_path))
    memory_manager = MemoryManager(workspace_manager)
    loader = SkillLoader(workspace_manager)

    registry = ToolRegistry()
    registry.register(FileTool(workspace_manager))
    tool_executor = ToolExecutor(registry)

    loader.upsert_skill_markdown("main", "file_read", FILE_SKILL_MD)
    assert loader.list_skill_names("main")

    # 仅验证依赖可协同初始化，确保 Skill 系统对运行时友好。
    assert memory_manager.status("main")["agent_id"] == "main"
    assert tool_executor is not None
