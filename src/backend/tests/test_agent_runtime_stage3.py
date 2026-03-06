from pathlib import Path
from types import SimpleNamespace

from app.agent.planner import Planner
from app.agent.prompt_builder import PromptBuilder
from app.agent.types import ModelOutput
from app.agent.runtime import AgentRuntime
from app.memory.manager import MemoryManager
from app.models.message import ChatMessage, Role
from app.skills.loader import SkillLoader
from app.tools.builtins.file_tool import FileTool
from app.tools.builtins.workspace_tool import WorkspaceTool
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.workspace.manager import WorkspaceManager


def _settings(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        model_provider="OpenAI",
        openai_base_url="",
        openai_model="gpt-5.3",
        openai_api_key="",
        openai_reasoning_effort="medium",
        workspace_root=str(tmp_path),
    )


def _build_runtime(tmp_path: Path) -> AgentRuntime:
    workspace_manager = WorkspaceManager(str(tmp_path))
    memory_manager = MemoryManager(workspace_manager)
    skill_loader = SkillLoader(workspace_manager)

    registry = ToolRegistry()
    registry.register(FileTool(workspace_manager))
    registry.register(WorkspaceTool(workspace_manager))
    tool_executor = ToolExecutor(registry)

    return AgentRuntime.from_settings(
        settings=_settings(tmp_path),
        workspace_manager=workspace_manager,
        memory_manager=memory_manager,
        skill_loader=skill_loader,
        tool_executor=tool_executor,
    )


def test_agent_object_and_loop_with_tool_write(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)

    history = [ChatMessage(role=Role.USER, content="请帮我写文件")]
    result = runtime.run_turn(
        agent_id="main",
        session_id="s1",
        user_message="/write notes/demo.txt hello-stage3",
        history=history,
    )

    import asyncio

    turn = asyncio.run(result)

    assert turn.reply
    assert turn.iterations >= 1
    assert any("tool_result:" in item for item in turn.memory_entries)

    snapshot = runtime.get_agent_snapshot("main")
    assert snapshot is not None
    assert snapshot["agent_id"] == "main"
    assert snapshot["workspace"]
    assert snapshot["memory"]["entries"] >= 1
    assert snapshot["current_task"]["status"] == "completed"


def test_planner_and_prompt_builder_stage3() -> None:
    planner = Planner(max_iterations=3)
    model_output = ModelOutput(
        text="需要访问网址信息",
        should_call_tool=True,
        should_continue=True,
        tool_hint="http",
    )

    plan = planner.plan(
        user_message="请访问 https://example.com 获取内容",
        model_output=model_output,
        iteration=0,
        tool_traces=[],
    )
    assert plan.tool_calls
    assert plan.tool_calls[0].name == "http"
    assert plan.continue_thinking is True
    assert plan.finish_task is False

    prompt_builder = PromptBuilder()
    prompt = prompt_builder.build(
        context_block="RULES: keep concise",
        history=[ChatMessage(role=Role.USER, content="hi")],
        memories=["user likes python"],
        skills=[],
        matched_skills=[],
        user_message="帮我总结",
        scratchpad="thinking...",
    )
    assert "[CONTEXT]" in prompt.full_prompt
    assert "[MEMORY]" in prompt.full_prompt
    assert "[USER]" in prompt.full_prompt


def test_natural_language_write_supports_unicode_filename_and_content(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)

    import asyncio

    turn = asyncio.run(
        runtime.run_turn(
            agent_id="main",
            session_id="s-write-cn",
            user_message='在工作区根目录创建“你好124.txt”，并且写入数据12314561',
            history=[],
        )
    )

    workspace = Path(runtime.get_agent_snapshot("main")["workspace"])
    target = workspace / "你好124.txt"
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "12314561"
    assert turn.reply


def test_planner_uses_workspace_context_for_bugfix_request_without_path() -> None:
    planner = Planner(max_iterations=3)
    model_output = ModelOutput(
        text="该任务可能需要工具信息支撑，先尝试工具调用。",
        should_call_tool=True,
        should_continue=True,
        tool_hint="file",
    )

    plan = planner.plan(
        user_message="The webpage I opened cannot write files. Help me fix the bug. The project is already open in VSCode.",
        model_output=model_output,
        iteration=0,
        tool_traces=[],
    )

    assert plan.tool_calls
    assert plan.tool_calls[0].name == "workspace"
    assert plan.tool_calls[0].args == {"action": "list"}
