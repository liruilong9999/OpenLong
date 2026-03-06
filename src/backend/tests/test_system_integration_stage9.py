import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.agent.runtime import AgentRuntime
from app.channel.manager import ChannelManager
from app.core.events import EventBus
from app.gateway.agent_manager import AgentManager
from app.gateway.model_router import ModelRouter
from app.gateway.runtime import GatewayRuntime
from app.gateway.session_manager import SessionManager
from app.gateway.task_queue import TaskQueue
from app.gateway.websocket import WebSocketHub
from app.memory.manager import MemoryManager
from app.self_evolution.engine import SelfEvolutionEngine
from app.skills.loader import SkillLoader
from app.tools.builtins.file_tool import FileTool
from app.tools.builtins.http_tool import HttpTool
from app.tools.builtins.shell_tool import ShellTool
from app.tools.builtins.time_tool import TimeTool
from app.tools.builtins.workspace_tool import WorkspaceTool
from app.tools.executor import ToolExecutor
from app.tools.logger import ToolExecutionLogStore
from app.tools.permissions import ToolPermissionManager
from app.tools.registry import ToolRegistry
from app.tools.sandbox import ToolSandbox
from app.workspace.manager import WorkspaceManager


def _build_runtime(tmp_path: Path, project_root: Path | None = None) -> GatewayRuntime:
    settings = SimpleNamespace(
        app_name="OpenLong",
        environment="test",
        workspace_root=str(tmp_path / "workspace"),
        model_provider="OpenAI",
        openai_base_url="",
        openai_model="gpt-5.3",
        openai_reasoning_effort="medium",
        openai_api_key="",
        tool_shell_enabled=False,
        tool_allowlist="file,http,shell,time,workspace",
        tool_denylist="",
        tool_confirmation_required="shell",
        tool_log_limit=500,
    )

    event_bus = EventBus()
    session_manager = SessionManager()
    websocket_hub = WebSocketHub()
    workspace_manager = WorkspaceManager(settings.workspace_root, project_root=str(project_root) if project_root else None)
    memory_manager = MemoryManager(workspace_manager, event_bus=event_bus)
    skill_loader = SkillLoader(workspace_manager)

    tool_registry = ToolRegistry()
    tool_registry.register(FileTool(workspace_manager))
    tool_registry.register(HttpTool())
    tool_registry.register(ShellTool(enabled=settings.tool_shell_enabled))
    tool_registry.register(TimeTool())
    tool_registry.register(WorkspaceTool(workspace_manager))
    tool_executor = ToolExecutor(
        tool_registry,
        event_bus=event_bus,
        permission_manager=ToolPermissionManager.from_csv(
            allowlist_csv=settings.tool_allowlist,
            denylist_csv=settings.tool_denylist,
            confirmation_csv=settings.tool_confirmation_required,
        ),
        sandbox=ToolSandbox(),
        log_store=ToolExecutionLogStore(max_records=settings.tool_log_limit),
    )

    agent_runtime = AgentRuntime.from_settings(
        settings=settings,
        workspace_manager=workspace_manager,
        memory_manager=memory_manager,
        skill_loader=skill_loader,
        tool_executor=tool_executor,
    )

    runtime = GatewayRuntime(
        settings=settings,
        session_manager=session_manager,
        agent_manager=AgentManager(agent_runtime),
        model_router=ModelRouter(settings, event_bus=event_bus),
        task_queue=TaskQueue(event_bus=event_bus),
        websocket_hub=websocket_hub,
        event_bus=event_bus,
        workspace_manager=workspace_manager,
        memory_manager=memory_manager,
        skill_loader=skill_loader,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        channel_manager=ChannelManager(),
        self_evolution_engine=SelfEvolutionEngine(),
        agent_runtime=agent_runtime,
    )
    runtime._register_event_handlers()
    return runtime


def test_full_system_integration_flow(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)

    runtime.create_workspace(agent_id="main", template_name="coding", agent_type="coding", overwrite=True)
    runtime.workspace_manager.update_context("main", "USER", "用户喜欢 Python 和简洁回复", dynamic_only=True)
    runtime.workspace_manager.update_context("main", "STYLE", "请优先给出结论", dynamic_only=True)

    skill_markdown = """# FileWriter

## 技能说明
写入工作区文件。

## 触发条件
- write
- 文件
- 保存

## 参数说明
- path(path,required): 文件路径
- content(string,required): 文件内容

## 示例
- /write notes/a.txt hello
"""
    runtime.skill_loader.upsert_skill_markdown("main", "file_writer", skill_markdown)

    result = asyncio.run(
        runtime.handle_user_message(
            session_id="integration-s1",
            user_message="/write notes/integration.txt hello-integration",
            preferred_agent_id="main",
            source="test",
        )
    )

    assert result["session_id"] == "integration-s1"
    assert result["agent_id"] == "main"
    assert result["reply"]
    assert result["task_id"]

    workspace = Path(runtime.workspace_manager.load_workspace("main")["path"])
    assert (workspace / "notes" / "integration.txt").exists()
    assert (workspace / "notes" / "integration.txt").read_text(encoding="utf-8") == "hello-integration"

    sessions = runtime.dashboard_sessions()
    assert any(item["session_id"] == "integration-s1" for item in sessions)

    memory = runtime.dashboard_memory("main")
    assert memory["entries"] >= 1
    assert memory["recent_items"]

    skills = runtime.dashboard_skills("main")
    assert skills["count"] >= 1

    context = runtime.get_agent_context("main")
    assert "RULES.md" in context["prompt_block"]
    assert "USER.md" in context["prompt_block"]

    workspace_logs = runtime.workspace_logs("main", limit=50)
    assert workspace_logs["items"]
    assert any(item["event_name"] == "tool.execution.completed" for item in workspace_logs["items"])

    tool_logs = runtime.tool_logs(limit=20)
    assert tool_logs["stats"]["total"] >= 1

    dashboard = runtime.dashboard_workspaces()
    assert dashboard["items"]
    assert dashboard["templates"]["templates"]


def test_conversation_followups_and_time(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    runtime.create_workspace(agent_id="main", template_name="default", agent_type="general", overwrite=True)

    first = asyncio.run(
        runtime.handle_user_message(
            session_id="follow-s1",
            user_message="工作目录下创建文件夹test_temp",
            preferred_agent_id="main",
            source="test",
        )
    )
    assert "created dir: test_temp" in first["reply"]

    second = asyncio.run(
        runtime.handle_user_message(
            session_id="follow-s1",
            user_message="创建好了吗？",
            preferred_agent_id="main",
            source="test",
        )
    )
    assert "已经创建好了" in second["reply"]

    third = asyncio.run(
        runtime.handle_user_message(
            session_id="follow-s2",
            user_message="现在几点了",
            preferred_agent_id="main",
            source="test",
        )
    )
    assert "工具执行完成" in third["reply"]
    assert "time" in third["reply"]


def test_write_command_targets_project_file_when_repo_path_is_requested(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    (project_root / "src" / "backend").mkdir(parents=True, exist_ok=True)
    runtime = _build_runtime(tmp_path, project_root=project_root)

    result = asyncio.run(
        runtime.handle_user_message(
            session_id="project-write-s1",
            user_message="/write src/backend/from-web.txt hello-project",
            preferred_agent_id="main",
            source="test",
        )
    )

    assert result["reply"]
    assert (project_root / "src" / "backend" / "from-web.txt").read_text(encoding="utf-8") == "hello-project"
    assert not (Path(runtime.workspace_manager.load_workspace("main")["path"]) / "src" / "backend" / "from-web.txt").exists()
