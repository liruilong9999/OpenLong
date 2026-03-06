from __future__ import annotations

import asyncio
from typing import Any

from app.tools.types import ToolParameterSpec, ToolResult, ToolSpec


class ShellTool:
    spec = ToolSpec(
        name="shell",
        description="Execute a shell command under sandbox constraints.",
        parameters=[
            ToolParameterSpec(name="input", param_type="string", required=True, description="shell command"),
            ToolParameterSpec(name="timeout", param_type="number", required=False, description="timeout seconds", default=15.0),
        ],
        returns="stdout or stderr",
    )

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled

    async def run(self, **kwargs: Any) -> ToolResult:
        if not self._enabled:
            return ToolResult(success=False, content="shell tool is disabled")

        command = str(kwargs.get("input", "")).strip()
        if not command:
            return ToolResult(success=False, content="missing command")

        timeout = float(kwargs.get("timeout", 15.0))
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            process.kill()
            return ToolResult(success=False, content="command timeout")

        output = (stdout or b"").decode("utf-8", errors="ignore").strip()
        error = (stderr or b"").decode("utf-8", errors="ignore").strip()

        if process.returncode != 0:
            return ToolResult(success=False, content=error or output or "command failed")
        return ToolResult(success=True, content=output or "ok")
