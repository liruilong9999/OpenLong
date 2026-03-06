from __future__ import annotations

from typing import Any

from app.tools.types import Tool, ToolSpec


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.spec.name] = tool

    def unregister(self, tool_name: str) -> bool:
        return self._tools.pop(tool_name, None) is not None

    def get(self, tool_name: str) -> Tool | None:
        return self._tools.get(tool_name)

    def list_tools(self) -> list[str]:
        return sorted(self._tools.keys())

    def list_specs(self) -> list[ToolSpec]:
        specs = [tool.spec for tool in self._tools.values()]
        specs.sort(key=lambda item: item.name)
        return specs

    def snapshot(self) -> dict[str, Any]:
        specs = self.list_specs()
        return {
            "count": len(specs),
            "tools": [item.to_dict() for item in specs],
        }
