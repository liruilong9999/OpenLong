from __future__ import annotations

from dataclasses import dataclass, field
import json
import re

from app.agent.types import ModelOutput, ToolCall, ToolCallTrace


_URL_PATTERN = re.compile(r"https?://[^\s]+", flags=re.IGNORECASE)
_FILE_NAME_PATTERN = re.compile(r"([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)")
_FOLDER_NAME_PATTERN = re.compile(r"文件夹\s*([A-Za-z0-9_\-]+)|目录\s*([A-Za-z0-9_\-]+)")


@dataclass(slots=True)
class TurnPlan:
    objective: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    continue_thinking: bool = False
    finish_task: bool = True
    reason: str = ""


class Planner:
    def __init__(self, max_iterations: int = 3) -> None:
        self._max_iterations = max_iterations

    def plan(
        self,
        *,
        user_message: str,
        model_output: ModelOutput,
        iteration: int,
        tool_traces: list[ToolCallTrace],
    ) -> TurnPlan:
        tool_calls = self._decide_tool_calls(
            user_message=user_message,
            model_output=model_output,
            iteration=iteration,
            tool_traces=tool_traces,
        )

        can_continue = iteration + 1 < self._max_iterations
        continue_thinking = False
        finish_task = True
        reason = "model_decision"

        if tool_calls and can_continue:
            continue_thinking = True
            finish_task = False
            reason = "tool_execution_required"
        elif model_output.should_continue and can_continue and not tool_traces:
            continue_thinking = True
            finish_task = False
            reason = "model_requested_more_reasoning"
        elif tool_traces and iteration == 0 and can_continue:
            continue_thinking = True
            finish_task = False
            reason = "post_tool_synthesis"

        if tool_traces and iteration > 0:
            continue_thinking = False
            finish_task = True
            reason = "tool_result_ready"

        if not can_continue:
            continue_thinking = False
            finish_task = True

        objective = "complete user request"
        if tool_calls:
            objective = "execute tool calls and synthesize result"

        return TurnPlan(
            objective=objective,
            tool_calls=tool_calls,
            continue_thinking=continue_thinking,
            finish_task=finish_task,
            reason=reason,
        )

    def _decide_tool_calls(
        self,
        *,
        user_message: str,
        model_output: ModelOutput,
        iteration: int,
        tool_traces: list[ToolCallTrace],
    ) -> list[ToolCall]:
        if tool_traces or iteration > 0:
            return []

        explicit = self._explicit_tool_command(user_message)
        if explicit:
            return explicit

        shorthand = self._shorthand_commands(user_message)
        if shorthand:
            return shorthand

        natural = self._natural_language_commands(user_message)
        if natural:
            return natural

        if not model_output.should_call_tool:
            return []

        return self._tool_call_from_hint(user_message=user_message, tool_hint=model_output.tool_hint)

    def _explicit_tool_command(self, user_message: str) -> list[ToolCall]:
        if not user_message.startswith("/tool "):
            return []

        parts = user_message.split(maxsplit=2)
        tool_name = parts[1] if len(parts) > 1 else ""
        raw_payload = parts[2] if len(parts) > 2 else ""

        if not tool_name:
            return []

        args: dict[str, object] = {}
        if raw_payload:
            stripped = raw_payload.strip()
            if stripped.startswith("{") and stripped.endswith("}"):
                try:
                    parsed = json.loads(stripped)
                    if isinstance(parsed, dict):
                        args = parsed
                except json.JSONDecodeError:
                    args = {"input": raw_payload}
            else:
                args = {"input": raw_payload}

        return [ToolCall(name=tool_name, args=args, reason="explicit_tool_command")]

    def _shorthand_commands(self, user_message: str) -> list[ToolCall]:
        if user_message.startswith("/read "):
            path = user_message[len("/read ") :].strip()
            if path:
                return [ToolCall(name="file", args={"action": "read", "path": path}, reason="read_command")]

        if user_message.startswith("/write "):
            payload = user_message[len("/write ") :].strip()
            parts = payload.split(maxsplit=1)
            if len(parts) == 2:
                return [ToolCall(name="file", args={"action": "write", "path": parts[0], "content": parts[1]}, reason="write_command")]

        if user_message.startswith("/http "):
            url = user_message[len("/http ") :].strip()
            if url:
                return [ToolCall(name="http", args={"method": "GET", "url": url}, reason="http_command")]

        if user_message.startswith("/shell "):
            command = user_message[len("/shell ") :].strip()
            if command:
                return [ToolCall(name="shell", args={"input": command}, reason="shell_command")]

        return []

    def _natural_language_commands(self, user_message: str) -> list[ToolCall]:
        normalized = user_message.replace("，", ",").strip()
        lower = normalized.lower()

        if any(token in normalized for token in ["创建文件夹", "创建目录", "新建文件夹", "新建目录"]):
            folder_match = _FOLDER_NAME_PATTERN.search(normalized)
            folder_name = next((item for item in folder_match.groups() if item), None) if folder_match else None
            if folder_name:
                return [ToolCall(name="file", args={"action": "mkdir", "path": folder_name}, reason="natural_language_mkdir")]

        if any(token in normalized for token in ["工作目录", "当前目录", "workspace", "工作区"]):
            return [ToolCall(name="workspace", args={"action": "info"}, reason="workspace_location_info")]

        if any(token in normalized for token in ["创建文件", "新建文件", "写入文件", "保存文件"]):
            file_match = _FILE_NAME_PATTERN.search(normalized)
            if file_match:
                file_name = file_match.group(1)
                return [ToolCall(name="file", args={"action": "write", "path": file_name, "content": ""}, reason="natural_language_file_create")]

        if any(token in normalized for token in ["现在几点", "当前时间", "几点了", "时间是多少"]):
            return [ToolCall(name="time", args={"format": "human"}, reason="natural_language_time")]

        if any(token in lower for token in ["readme", "读取文件", "打开文件", "查看文件"]):
            file_match = _FILE_NAME_PATTERN.search(normalized)
            path = file_match.group(1) if file_match else "README.md"
            return [ToolCall(name="file", args={"action": "read", "path": path}, reason="natural_language_file_read")]

        if any(token in lower for token in ["访问", "请求", "抓取", "api", "网址", "网页"]):
            url_match = _URL_PATTERN.search(normalized)
            if url_match:
                return [ToolCall(name="http", args={"method": "GET", "url": url_match.group(0)}, reason="natural_language_http")]

        return []

    def _tool_call_from_hint(self, user_message: str, tool_hint: str | None) -> list[ToolCall]:
        if not tool_hint:
            return []

        hint = tool_hint.lower()
        if hint == "http":
            url_match = _URL_PATTERN.search(user_message)
            if url_match:
                return [ToolCall(name="http", args={"method": "GET", "url": url_match.group(0)}, reason="model_http_hint")]
            return []

        if hint == "file":
            file_match = _FILE_NAME_PATTERN.search(user_message)
            path = file_match.group(1) if file_match else "README.md"
            action = "write" if any(token in user_message for token in ["创建", "写", "保存"]) and file_match else "read"
            args = {"action": action, "path": path}
            if action == "write":
                args["content"] = ""
            return [ToolCall(name="file", args=args, reason="model_file_hint")]

        if hint == "workspace":
            return [ToolCall(name="workspace", args={"action": "info"}, reason="model_workspace_hint")]

        if hint == "time":
            return [ToolCall(name="time", args={"format": "human"}, reason="model_time_hint")]

        if hint == "shell":
            return [ToolCall(name="shell", args={"input": "Get-Location"}, reason="model_shell_hint_default")]

        return []
