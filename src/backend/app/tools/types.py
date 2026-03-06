from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class ToolResult:
    success: bool
    content: str
    data: dict[str, Any] = field(default_factory=dict)


class Tool(Protocol):
    name: str

    async def run(self, **kwargs: Any) -> ToolResult:
        ...
