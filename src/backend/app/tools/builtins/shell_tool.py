from __future__ import annotations

import asyncio
from typing import Any

from app.tools.types import ToolResult


class ShellTool:
    name = "shell"

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled

    async def run(self, **kwargs: Any) -> ToolResult:
        if not self._enabled:
            return ToolResult(success=False, content="shell tool is disabled")

        command = str(kwargs.get("input", "")).strip()
        if not command:
            return ToolResult(success=False, content="missing command")

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        output = (stdout or b"").decode("utf-8", errors="ignore").strip()
        error = (stderr or b"").decode("utf-8", errors="ignore").strip()

        if process.returncode != 0:
            return ToolResult(success=False, content=error or output or "command failed")
        return ToolResult(success=True, content=output or "ok")
