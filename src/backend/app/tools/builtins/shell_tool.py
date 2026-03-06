from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.tools.types import ToolParameterSpec, ToolResult, ToolSpec


_HIGH_RISK_PATTERNS = [
    "rm -rf",
    "del /f /q",
    "format ",
    "mkfs",
    "shutdown",
    "reboot",
    "reg delete",
    "net user",
    "curl ",
    "| sh",
    "| bash",
    "powershell -enc",
    "git clean -fd",
    "git reset --hard",
]

_SAFE_READ_PREFIXES = [
    "echo",
    "dir",
    "ls",
    "pwd",
    "type",
    "cat",
    "get-childitem",
    "get-location",
    "where",
    "python --version",
    "pip --version",
    "pytest --version",
    "node --version",
    "npm --version",
    "git status",
    "git diff",
    "git log",
    "git branch",
]

_BUILD_PREFIXES = [
    "pytest",
    "python -m pytest",
    "python -c",
    "python.exe -c",
    "npm run build",
    "npm.cmd run build",
    "vite build",
    "npm run dev",
    "npm.cmd run dev",
]

_INSTALL_PREFIXES = [
    "npm install",
    "npm.cmd install",
    "npm ci",
    "npm.cmd ci",
    "pnpm install",
    "yarn install",
    "pip install",
    "python -m pip install",
]


def classify_shell_command(command: str) -> str:
    lowered = str(command or "").strip().lower()
    if any(pattern in lowered for pattern in _HIGH_RISK_PATTERNS):
        return "high_risk"
    if any(lowered.startswith(prefix) for prefix in _INSTALL_PREFIXES):
        return "package_install"
    if any(lowered.startswith(prefix) for prefix in _BUILD_PREFIXES):
        return "build"
    if any(lowered.startswith(prefix) for prefix in _SAFE_READ_PREFIXES):
        return "safe_read"
    return "unknown"


def allowed_shell_prefixes() -> list[str]:
    return [*_SAFE_READ_PREFIXES, *_BUILD_PREFIXES, *_INSTALL_PREFIXES]


class ShellTool:
    spec = ToolSpec(
        name="shell",
        description="Execute shell commands with approval, cwd control, and streamed output.",
        parameters=[
            ToolParameterSpec(name="input", param_type="string", required=True, description="shell command"),
            ToolParameterSpec(name="timeout", param_type="number", required=False, description="timeout seconds", default=120.0),
            ToolParameterSpec(name="cwd", param_type="string", required=False, description="working directory, relative to project or agent workspace"),
            ToolParameterSpec(name="cwd_scope", param_type="string", required=False, description="auto, project, or workspace", default="project"),
            ToolParameterSpec(name="agent_id", param_type="string", required=False, description="target agent workspace"),
        ],
        returns="stdout, stderr, exit code, command category, and working directory",
    )

    def __init__(self, enabled: bool = False, project_root: str | Path | None = None, workspace_root: str | Path | None = None) -> None:
        self._enabled = enabled
        self._project_root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
        self._workspace_root = Path(workspace_root).resolve() if workspace_root else self._project_root

    async def run(self, **kwargs: Any) -> ToolResult:
        if not self._enabled:
            return ToolResult(success=False, content="shell tool is disabled")

        command = str(kwargs.get("input", "")).strip()
        if not command:
            return ToolResult(success=False, content="missing command")

        timeout = float(kwargs.get("timeout", 120.0))
        category = classify_shell_command(command)
        cwd = self._resolve_cwd(
            cwd=str(kwargs.get("cwd", "") or ""),
            cwd_scope=str(kwargs.get("cwd_scope", "project") or "project"),
            agent_id=str(kwargs.get("agent_id", "main") or "main"),
        )
        stream_handler = kwargs.get("stream_handler")

        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        async def _consume(stream: asyncio.StreamReader | None, stream_name: str, target: list[str]) -> None:
            if stream is None:
                return
            while True:
                chunk = await stream.readline()
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="ignore")
                target.append(text)
                await self._notify_stream(stream_handler, stream_name=stream_name, text=text)

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    _consume(process.stdout, "stdout", stdout_chunks),
                    _consume(process.stderr, "stderr", stderr_chunks),
                    process.wait(),
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            return ToolResult(
                success=False,
                content="command timeout",
                data={
                    "command": command,
                    "cwd": str(cwd),
                    "category": category,
                    "exit_code": None,
                    "stdout": "".join(stdout_chunks).strip(),
                    "stderr": "".join(stderr_chunks).strip(),
                },
            )

        stdout_text = "".join(stdout_chunks).strip()
        stderr_text = "".join(stderr_chunks).strip()
        exit_code = process.returncode
        content = stdout_text or stderr_text or "ok"

        return ToolResult(
            success=exit_code == 0,
            content=content,
            data={
                "command": command,
                "cwd": str(cwd),
                "category": category,
                "exit_code": exit_code,
                "stdout": stdout_text,
                "stderr": stderr_text,
            },
        )

    async def _notify_stream(
        self,
        handler: Callable[..., Any] | None,
        *,
        stream_name: str,
        text: str,
    ) -> None:
        if handler is None:
            return
        outcome = handler(stream=stream_name, text=text)
        if inspect.isawaitable(outcome):
            await outcome

    def _resolve_cwd(self, *, cwd: str, cwd_scope: str, agent_id: str) -> Path:
        scope = cwd_scope.strip().lower() or "project"
        workspace_root = (self._workspace_root / agent_id).resolve()
        workspace_root.mkdir(parents=True, exist_ok=True)

        if not cwd:
            return self._project_root if scope != "workspace" else workspace_root

        raw = Path(cwd)
        if raw.is_absolute():
            resolved = raw.resolve()
            if self._is_within(resolved, self._project_root) or self._is_within(resolved, workspace_root):
                return resolved
            raise ValueError("cwd escapes allowed roots")

        if scope == "workspace":
            resolved = (workspace_root / raw).resolve()
            if not self._is_within(resolved, workspace_root):
                raise ValueError("cwd escapes workspace")
            resolved.mkdir(parents=True, exist_ok=True)
            return resolved

        resolved = (self._project_root / raw).resolve()
        if self._is_within(resolved, self._project_root):
            resolved.mkdir(parents=True, exist_ok=True)
            return resolved

        fallback = (workspace_root / raw).resolve()
        if not self._is_within(fallback, workspace_root):
            raise ValueError("cwd escapes allowed roots")
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    def _is_within(self, target: Path, root: Path) -> bool:
        return target == root or root in target.parents
