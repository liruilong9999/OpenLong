from __future__ import annotations

from typing import Any

from app.tools.registry import ToolRegistry
from app.tools.types import ToolResult


class ToolExecutor:
    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def execute(self, tool_name: str, **kwargs: Any) -> ToolResult:
        tool = self._registry.get(tool_name)
        if tool is None:
            return ToolResult(success=False, content=f"tool not found: {tool_name}")

        return await tool.run(**kwargs)
