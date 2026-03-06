from __future__ import annotations

from datetime import datetime
from typing import Any

from app.tools.types import ToolParameterSpec, ToolResult, ToolSpec


class TimeTool:
    spec = ToolSpec(
        name="time",
        description="Return the current local system time.",
        parameters=[
            ToolParameterSpec(name="format", param_type="string", required=False, description="iso or human", default="human"),
        ],
        returns="current time string",
    )

    async def run(self, **kwargs: Any) -> ToolResult:
        mode = str(kwargs.get("format", "human")).lower()
        now = datetime.now().astimezone()
        if mode == "iso":
            content = now.isoformat()
        else:
            content = now.strftime("%Y-%m-%d %H:%M:%S %Z")
        return ToolResult(success=True, content=content, data={"iso": now.isoformat()})
