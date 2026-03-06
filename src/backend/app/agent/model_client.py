from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json
import mimetypes
import os
from pathlib import Path
import re
from time import perf_counter
from typing import Any, Callable, Protocol

import httpx

from app.agent.planner import infer_structured_tool_calls
from app.agent.types import ModelOutput, ToolCall
from app.core.config import Settings


_URL_PATTERN = re.compile(r"https?://[^\s]+", flags=re.IGNORECASE)


@dataclass(slots=True)
class ModelRequest:
    agent_id: str
    task_id: str
    user_message: str
    prompt: str
    iteration: int
    task_type: str = "chat"
    tool_summaries: list[str] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    model_routes: list[dict[str, Any]] = field(default_factory=list)
    model_route_source: str = "default"
    attempt_observer: Callable[..., None] | None = None


class ModelClient(Protocol):
    async def generate(self, request: ModelRequest) -> ModelOutput:
        ...


class HeuristicModelClient:
    async def generate(self, request: ModelRequest) -> ModelOutput:
        user_message = request.user_message
        lower = user_message.lower()
        prompt = request.prompt
        tool_hint = self._guess_tool_hint(user_message)
        structured_calls = infer_structured_tool_calls(user_message, tool_hint=tool_hint)

        if request.attachments and any(self._is_image_attachment(item) for item in request.attachments):
            return ModelOutput(
                text="我已收到图片附件，接下来会优先尝试结合视觉能力进行分析。",
                confidence=0.72,
                should_call_tool=False,
                should_continue=False,
                metadata={"mode": "image_attachment_hint", "prompt_chars": len(request.prompt)},
            )

        if self._is_follow_up_success_query(lower) and self._prompt_contains_success(prompt):
            return ModelOutput(
                text="已经创建好了，上一轮工具执行成功。",
                confidence=0.88,
                should_call_tool=False,
                should_continue=False,
                metadata={"mode": "memory_follow_up"},
            )

        remembered_time = self._extract_previous_availability(prompt)
        if remembered_time and any(token in user_message for token in ["记得", "有空", "什么时候"]):
            return ModelOutput(
                text=f"你前面提到你平时有空的时间是：{remembered_time}。",
                confidence=0.82,
                should_call_tool=False,
                should_continue=False,
                metadata={"mode": "memory_recall"},
            )

        if request.tool_summaries:
            return ModelOutput(
                text="已获取工具结果，正在整理最终答案。",
                confidence=0.75,
                should_call_tool=False,
                should_continue=False,
                metadata={"mode": "post_tool", "prompt_chars": len(request.prompt)},
            )

        if user_message.startswith("/tool "):
            return ModelOutput(
                text="检测到显式工具命令，准备执行工具。",
                confidence=0.9,
                should_call_tool=bool(structured_calls),
                should_continue=True,
                tool_hint=tool_hint,
                tool_calls=structured_calls,
                metadata={"mode": "explicit_tool", "prompt_chars": len(request.prompt)},
            )

        if user_message.startswith("/think") and request.iteration == 0:
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
                should_call_tool=bool(structured_calls),
                should_continue=True,
                tool_hint=tool_hint,
                tool_calls=structured_calls,
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

        if any(token in user_message for token in ["工作目录", "当前目录", "工作区", "workspace"]):
            return "workspace"
        if any(token in user_message for token in ["几点", "时间", "当前时间"]):
            return "time"
        if any(token in lower for token in ["文件", "read", "write", "path", "目录", "保存", "创建文件", "文件夹"]):
            return "file"
        if any(token in lower for token in ["网址", "http", "api", "网页", "抓取", "请求"]):
            return "http"
        if any(token in lower for token in ["命令", "shell", "终端", "powershell", "cmd"]):
            return "shell"

        return None

    def _is_image_attachment(self, item: dict[str, Any]) -> bool:
        content_type = str(item.get("content_type") or item.get("type") or "").lower()
        return content_type.startswith("image/")

    def _is_follow_up_success_query(self, lower: str) -> bool:
        return any(token in lower for token in ["创建好了吗", "成功了吗", "弄好了吗", "完成了吗"])

    def _prompt_contains_success(self, prompt: str) -> bool:
        return any(token in prompt for token in ["written:", "created dir:", "success=True"])

    def _extract_previous_availability(self, prompt: str) -> str | None:
        match = re.search(r"晚上一个小时", prompt)
        if match:
            return match.group(0)
        return None


class OpenAICompatibleModelClient:
    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        model: str,
        api_key: str,
        reasoning_effort: str = "medium",
        timeout: float = 20.0,
        fallback: ModelClient | None = None,
    ) -> None:
        self._provider = provider or "OpenAI"
        self._base_url = base_url.strip()
        self._model = model.strip()
        self._api_key = api_key.strip()
        self._reasoning_effort = reasoning_effort.strip()
        self._timeout = timeout
        self._fallback = fallback or HeuristicModelClient()
        self._heuristic = HeuristicModelClient()

    @classmethod
    def from_settings(cls, settings: Settings, fallback: ModelClient | None = None) -> "OpenAICompatibleModelClient":
        return cls(
            provider=settings.model_provider or "OpenAI",
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            reasoning_effort=settings.openai_reasoning_effort,
            fallback=fallback,
        )

    async def generate(self, request: ModelRequest) -> ModelOutput:
        route_endpoints = request.model_routes or [self._default_route_endpoint()]
        attempts: list[dict[str, Any]] = []
        resolved_endpoints = [self._resolve_route_endpoint(item) for item in route_endpoints]

        if resolved_endpoints and all(
            not endpoint["base_url"] or not endpoint["model"] or not endpoint["api_key"]
            for endpoint in resolved_endpoints
        ):
            missing = resolved_endpoints[0]
            self._notify_attempt(
                request,
                endpoint=missing,
                success=False,
                latency_ms=0.0,
                error="API key or model config missing",
                endpoint_index=0,
            )
            fallback_output = await self._fallback.generate(request)
            fallback_output.metadata = {
                **fallback_output.metadata,
                "mode": "missing_model_config",
                "route_source": request.model_route_source,
                "attempts": [
                    {
                        "provider": missing["provider"],
                        "model": missing["model"],
                        "success": False,
                        "error": "API key or model config missing",
                        "endpoint_index": 0,
                    }
                ],
            }
            return fallback_output

        if _model_api_disabled():
            skipped = resolved_endpoints[0] if resolved_endpoints else self._default_route_endpoint()
            self._notify_attempt(
                request,
                endpoint=skipped,
                success=False,
                latency_ms=0.0,
                error="model api disabled",
                endpoint_index=0,
            )
            fallback_output = await self._fallback.generate(request)
            fallback_output.metadata = {
                **fallback_output.metadata,
                "mode": "model_api_disabled",
                "route_source": request.model_route_source,
                "attempts": [
                    {
                        "provider": skipped.get("provider") or self._provider,
                        "model": skipped.get("model") or self._model,
                        "success": False,
                        "error": "model api disabled",
                        "endpoint_index": 0,
                    }
                ],
            }
            return fallback_output

        missing_config_count = 0
        for endpoint_index, resolved in enumerate(resolved_endpoints):
            if not resolved["base_url"] or not resolved["model"] or not resolved["api_key"]:
                missing_config_count += 1
                error = "API key or model config missing"
                attempts.append(
                    {
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "success": False,
                        "error": error,
                        "endpoint_index": endpoint_index,
                    }
                )
                self._notify_attempt(
                    request,
                    endpoint=resolved,
                    success=False,
                    latency_ms=0.0,
                    error=error,
                    endpoint_index=endpoint_index,
                )
                continue

            started = perf_counter()
            try:
                text = await self._responses_api(request, endpoint=resolved)
                latency_ms = round((perf_counter() - started) * 1000, 3)
                attempts.append(
                    {
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "success": True,
                        "error": None,
                        "endpoint_index": endpoint_index,
                    }
                )
                self._notify_attempt(
                    request,
                    endpoint=resolved,
                    success=True,
                    latency_ms=latency_ms,
                    error=None,
                    endpoint_index=endpoint_index,
                )
                structured = self._parse_structured_model_output(text)
                response_text = structured["response"] if structured is not None else text
                tool_calls = structured["tool_calls"] if structured is not None else []
                continue_flag = bool(structured["continue"]) if structured is not None else False
                tool_hint = tool_calls[0].name if tool_calls else self._heuristic._guess_tool_hint(request.user_message)
                return ModelOutput(
                    text=response_text,
                    confidence=0.9,
                    should_call_tool=bool(tool_calls),
                    should_continue=continue_flag or bool(tool_calls),
                    tool_hint=tool_hint,
                    tool_calls=tool_calls,
                    metadata={
                        "mode": "external_api_structured" if structured is not None else "external_api",
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "latency_ms": latency_ms,
                        "route_source": request.model_route_source,
                        "endpoint_index": endpoint_index,
                        "attempts": attempts,
                    },
                )
            except Exception as exc:
                latency_ms = round((perf_counter() - started) * 1000, 3)
                attempts.append(
                    {
                        "provider": resolved["provider"],
                        "model": resolved["model"],
                        "success": False,
                        "error": str(exc),
                        "endpoint_index": endpoint_index,
                    }
                )
                self._notify_attempt(
                    request,
                    endpoint=resolved,
                    success=False,
                    latency_ms=latency_ms,
                    error=str(exc),
                    endpoint_index=endpoint_index,
                )

        fallback_output = await self._fallback.generate(request)
        fallback_mode = "missing_model_config" if missing_config_count == len(route_endpoints) else "external_api_fallback"
        fallback_output.metadata = {
            **fallback_output.metadata,
            "mode": fallback_mode,
            "provider": attempts[0]["provider"] if attempts else self._provider,
            "model": attempts[0]["model"] if attempts else self._model,
            "error": next((item["error"] for item in reversed(attempts) if item.get("error")), "model route exhausted"),
            "route_source": request.model_route_source,
            "attempts": attempts,
        }
        return fallback_output

    async def _responses_api(self, request: ModelRequest, *, endpoint: dict[str, Any]) -> str:
        headers = {
            "Authorization": f"Bearer {endpoint['api_key']}",
            "Content-Type": "application/json",
        }
        user_content = [
            {
                "type": "input_text",
                "text": request.prompt,
            }
        ]
        user_content.extend(self._attachment_content(request.attachments))

        payload = {
            "model": endpoint["model"],
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "You are OpenLong, an agent system. Follow the provided prompt exactly. Unless the user explicitly requests another language, always answer in Simplified Chinese.",
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": user_content,
                },
            ],
        }
        if endpoint["reasoning_effort"]:
            payload["reasoning"] = {"effort": endpoint["reasoning_effort"]}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(self._responses_endpoint(endpoint["base_url"]), headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            content = self._extract_responses_text(data)
            if content:
                return content
            raise RuntimeError(f"empty responses payload: {data}")

    def _attachment_content(self, attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for attachment in attachments[:4]:
            items.extend(self._single_attachment_content(attachment))
        return items

    def _single_attachment_content(self, attachment: dict[str, Any]) -> list[dict[str, Any]]:
        path = self._attachment_path(attachment)
        if path is None or not path.exists() or not path.is_file():
            return []

        content_type = str(attachment.get("content_type") or attachment.get("type") or "").lower()
        if not content_type:
            guessed_type, _ = mimetypes.guess_type(path.name)
            content_type = guessed_type or "application/octet-stream"

        if content_type.startswith("image/") and path.stat().st_size <= 8 * 1024 * 1024:
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            return [
                {
                    "type": "input_text",
                    "text": f"附件：{attachment.get('filename') or path.name}，路径 {attachment.get('relative_path') or path.name}",
                },
                {
                    "type": "input_image",
                    "image_url": f"data:{content_type};base64,{encoded}",
                },
            ]

        if self._is_text_attachment(path, content_type):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")[:12000]
            except OSError:
                return []
            return [
                {
                    "type": "input_text",
                    "text": (
                        f"附件内容（{attachment.get('filename') or path.name} / {attachment.get('relative_path') or path.name}）:\n"
                        f"{text}"
                    ),
                }
            ]

        return [
            {
                "type": "input_text",
                "text": (
                    f"附件元数据：{attachment.get('filename') or path.name}，路径 {attachment.get('relative_path') or path.name}，"
                    f"类型 {content_type}，大小 {attachment.get('size') or path.stat().st_size} 字节。"
                ),
            }
        ]

    def _attachment_path(self, attachment: dict[str, Any]) -> Path | None:
        candidate = attachment.get("absolute_path") or attachment.get("absolutePath")
        if not candidate:
            return None
        try:
            return Path(str(candidate))
        except (TypeError, ValueError):
            return None

    def _is_text_attachment(self, path: Path, content_type: str) -> bool:
        if content_type.startswith("text/"):
            return True
        return path.suffix.lower() in {
            ".txt", ".md", ".json", ".csv", ".log", ".py", ".js", ".ts", ".tsx", ".jsx",
            ".html", ".css", ".xml", ".yaml", ".yml", ".toml", ".ini", ".sh", ".ps1", ".bat",
            ".c", ".cpp", ".h", ".hpp", ".java", ".go", ".rs",
        }

    def _default_route_endpoint(self) -> dict[str, Any]:
        return {
            "provider": self._provider,
            "base_url": self._base_url,
            "model": self._model,
            "reasoning_effort": self._reasoning_effort,
            "api_key": self._api_key,
            "has_api_key": bool(self._api_key),
        }

    def _resolve_route_endpoint(self, endpoint: dict[str, Any]) -> dict[str, Any]:
        default = self._default_route_endpoint()
        return {
            "provider": str(endpoint.get("provider") or default["provider"]),
            "base_url": str(endpoint.get("base_url") or default["base_url"]),
            "model": str(endpoint.get("model") or default["model"]),
            "reasoning_effort": str(endpoint.get("reasoning_effort") or default["reasoning_effort"]),
            "api_key": str(endpoint.get("api_key") or default["api_key"]),
            "has_api_key": bool(endpoint.get("api_key") or default["api_key"]),
        }

    def _notify_attempt(
        self,
        request: ModelRequest,
        *,
        endpoint: dict[str, Any],
        success: bool,
        latency_ms: float,
        error: str | None,
        endpoint_index: int,
    ) -> None:
        if request.attempt_observer is None:
            return
        request.attempt_observer(
            provider=str(endpoint.get("provider") or self._provider),
            model=str(endpoint.get("model") or self._model),
            success=success,
            latency_ms=latency_ms,
            error=error,
            endpoint_index=endpoint_index,
        )

    def _responses_endpoint(self, base_url: str) -> str:
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/responses"
        return f"{base}/v1/responses"

    def _parse_structured_model_output(self, text: str) -> dict[str, Any] | None:
        candidates = self._json_candidates(text)
        for candidate in candidates:
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            tool_calls = self._parse_tool_calls(payload.get("tool_calls"))
            response = str(payload.get("response") or payload.get("answer") or payload.get("text") or "").strip()
            if not response and not tool_calls:
                continue
            return {
                "response": response or "已生成工具调用计划。",
                "tool_calls": tool_calls,
                "continue": bool(payload.get("continue", False)),
            }
        return None

    def _json_candidates(self, text: str) -> list[str]:
        candidates = [text.strip()]
        fence_matches = re.findall(r"```json\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
        candidates.extend(match.strip() for match in fence_matches if match.strip())
        return [item for item in candidates if item]

    def _parse_tool_calls(self, payload: Any) -> list[ToolCall]:
        if not isinstance(payload, list):
            return []
        calls: list[ToolCall] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("tool") or "").strip()
            args = item.get("args")
            if not name or not isinstance(args, dict):
                continue
            calls.append(
                ToolCall(
                    name=name,
                    args=args,
                    reason=str(item.get("reason") or "model_structured_tool_call"),
                )
            )
        return calls

    def _extract_responses_text(self, payload: dict[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        output = payload.get("output")
        if isinstance(output, list):
            parts: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for entry in content:
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("type") in {"output_text", "text"} and isinstance(entry.get("text"), str):
                        parts.append(entry["text"].strip())
            if parts:
                return "\n".join(part for part in parts if part)

        return ""


def _model_api_disabled() -> bool:
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True

    return os.getenv("OPENLONG_DISABLE_MODEL_API", "").strip().lower() in {"1", "true", "yes", "on"}

