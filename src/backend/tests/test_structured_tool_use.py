import asyncio
from pathlib import Path

from app.agent.model_client import HeuristicModelClient, ModelRequest, OpenAICompatibleModelClient
from app.agent.planner import Planner
from app.agent.prompt_builder import PromptBuilder
from app.agent.types import ModelOutput, ToolCall
from app.tools.builtins.file_tool import FileTool
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.workspace.manager import WorkspaceManager


def test_prompt_builder_injects_tool_schema_block() -> None:
    prompt_builder = PromptBuilder()
    prompt = prompt_builder.build(
        context_block="RULES: concise",
        history=[],
        memories=[],
        skills=[],
        matched_skills=[],
        user_message="请读取 README",
        available_tools=[
            {
                "name": "file",
                "description": "Read and write files",
                "parameters": [
                    {"name": "action", "param_type": "string", "required": True},
                    {"name": "path", "param_type": "string", "required": True},
                ],
                "returns": "file content",
            }
        ],
    )

    assert "[TOOLS]" in prompt.full_prompt
    assert '"tool_calls"' in prompt.full_prompt
    assert "file: Read and write files" in prompt.full_prompt


def test_heuristic_model_client_returns_structured_tool_calls() -> None:
    client = HeuristicModelClient()

    output = asyncio.run(
        client.generate(
            ModelRequest(
                agent_id="main",
                task_id="t-struct",
                task_type="chat",
                user_message='创建文件 "notes/demo.txt" 内容是 hello-structured',
                prompt="[USER]\n创建文件",
                iteration=0,
            )
        )
    )

    assert output.should_call_tool is True
    assert output.tool_calls
    assert output.tool_calls[0].name == "file"
    assert output.tool_calls[0].args["action"] == "write"
    assert output.tool_calls[0].args["path"] == "notes/demo.txt"


def test_planner_prefers_structured_model_tool_calls() -> None:
    planner = Planner(max_iterations=3)
    model_output = ModelOutput(
        text="已生成工具调用",
        should_call_tool=True,
        should_continue=True,
        tool_calls=[
            ToolCall(name="file", args={"action": "mkdir", "path": "from-model"}, reason="model_structured_tool_call")
        ],
    )

    plan = planner.plan(
        user_message="创建目录 natural-fallback",
        model_output=model_output,
        iteration=0,
        tool_traces=[],
    )

    assert plan.tool_calls
    assert plan.tool_calls[0].args["path"] == "from-model"
    assert plan.reason == "tool_execution_required"


def test_openai_model_client_parses_structured_json_response(monkeypatch) -> None:
    async def fake_responses(self, request, *, endpoint):
        return '{"response":"先读取 README","tool_calls":[{"name":"file","args":{"action":"read","path":"README.md"},"reason":"需要读取说明文档"}],"continue":true}'

    monkeypatch.setattr("app.agent.model_client._model_api_disabled", lambda: False)
    monkeypatch.setattr(OpenAICompatibleModelClient, "_responses_api", fake_responses)

    client = OpenAICompatibleModelClient(
        provider="OpenAI",
        base_url="https://example.com/v1",
        model="gpt-structured",
        api_key="sk-test",
    )

    output = asyncio.run(
        client.generate(
            ModelRequest(
                agent_id="main",
                task_id="t-json",
                task_type="chat",
                user_message="请读取 README",
                prompt="[USER]\n请读取 README",
                iteration=0,
            )
        )
    )

    assert output.text == "先读取 README"
    assert output.should_call_tool is True
    assert output.tool_calls[0].name == "file"
    assert output.tool_calls[0].args["path"] == "README.md"


def test_tool_executor_attaches_standard_trace(tmp_path: Path) -> None:
    workspace_manager = WorkspaceManager(str(tmp_path / "workspace"))
    registry = ToolRegistry()
    registry.register(FileTool(workspace_manager))
    executor = ToolExecutor(registry)

    result = asyncio.run(
        executor.execute(
            "file",
            session_id="trace-s1",
            agent_id="main",
            action="write",
            path="notes/trace.txt",
            content="trace-ok",
        )
    )

    assert result.success is True
    assert "trace" in result.data
    trace = result.data["trace"]
    assert trace["tool_name"] == "file"
    assert trace["session_id"] == "trace-s1"
    assert trace["agent_id"] == "main"
    assert trace["success"] is True
    assert trace["latency_ms"] >= 0

