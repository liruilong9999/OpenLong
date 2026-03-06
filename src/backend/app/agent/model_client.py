from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Protocol

from app.agent.types import ModelOutput


_URL_PATTERN = re.compile(r"https?://[^\s]+", flags=re.IGNORECASE)


@dataclass(slots=True)
class ModelRequest:
    agent_id: str
    task_id: str
    user_message: str
    prompt: str
    iteration: int
    tool_summaries: list[str] = field(default_factory=list)


class ModelClient(Protocol):
    async def generate(self, request: ModelRequest) -> ModelOutput:
        ...


class HeuristicModelClient:
    async def generate(self, request: ModelRequest) -> ModelOutput:
        lower = request.user_message.lower()
        tool_hint = self._guess_tool_hint(request.user_message)

        if request.tool_summaries:
            return ModelOutput(
                text="已获取工具结果，正在整理最终答案。",
                confidence=0.75,
                should_call_tool=False,
                should_continue=False,
                metadata={"mode": "post_tool", "prompt_chars": len(request.prompt)},
            )

        if request.user_message.startswith("/tool "):
            return ModelOutput(
                text="检测到显式工具命令，准备执行工具。",
                confidence=0.9,
                should_call_tool=True,
                should_continue=True,
                tool_hint=tool_hint,
                metadata={"mode": "explicit_tool", "prompt_chars": len(request.prompt)},
            )

        if request.user_message.startswith("/think") and request.iteration == 0:
            return ModelOutput(
                text="继续思考中，将在下一轮给出结论。",
                confidence=0.7,
                should_call_tool=False,
                should_continue=True,
                metadata={"mode": "think", "prompt_chars": len(request.prompt)},
            )

        if tool_hint and request.iteration == 0:
            return ModelOutput(
                text="该任务可能需要工具信息支撑，先尝试工具调用。",
                confidence=0.65,
                should_call_tool=True,
                should_continue=True,
                tool_hint=tool_hint,
                metadata={"mode": "heuristic_tool", "prompt_chars": len(request.prompt)},
            )

        return ModelOutput(
            text=f"我已理解你的请求：{request.user_message[:160]}",
            confidence=0.6,
            should_call_tool=False,
            should_continue=False,
            metadata={"mode": "direct_answer", "prompt_chars": len(request.prompt)},
        )

    def _guess_tool_hint(self, user_message: str) -> str | None:
        lower = user_message.lower()
        if user_message.startswith("/tool "):
            parts = user_message.split(maxsplit=2)
            return parts[1] if len(parts) > 1 else None

        if user_message.startswith("/read") or user_message.startswith("/write"):
            return "file"
        if user_message.startswith("/http") or _URL_PATTERN.search(user_message):
            return "http"
        if user_message.startswith("/shell"):
            return "shell"

        if any(token in lower for token in ["文件", "read", "write", "path", "目录", "保存"]):
            return "file"
        if any(token in lower for token in ["网址", "http", "api", "网页", "抓取", "请求"]):
            return "http"
        if any(token in lower for token in ["命令", "shell", "终端", "powershell", "cmd"]):
            return "shell"

        return None
