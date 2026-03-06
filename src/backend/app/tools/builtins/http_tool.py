from __future__ import annotations

from typing import Any

import httpx

from app.tools.types import ToolParameterSpec, ToolResult, ToolSpec


class HttpTool:
    spec = ToolSpec(
        name="http",
        description="Send HTTP requests to remote services.",
        parameters=[
            ToolParameterSpec(name="method", param_type="string", required=False, description="HTTP method", default="GET"),
            ToolParameterSpec(name="url", param_type="string", required=True, description="target URL"),
            ToolParameterSpec(name="timeout", param_type="number", required=False, description="timeout seconds", default=20.0),
        ],
        returns="response status and text snippet",
    )

    async def run(self, **kwargs: Any) -> ToolResult:
        method = str(kwargs.get("method", "GET")).upper()
        url = str(kwargs.get("url", "")).strip()

        if not url:
            return ToolResult(success=False, content="missing url")

        timeout = float(kwargs.get("timeout", 20.0))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.request(method=method, url=url)
        snippet = response.text[:1500]

        return ToolResult(
            success=response.is_success,
            content=f"status={response.status_code}\n{snippet}",
            data={"status_code": response.status_code, "headers": dict(response.headers)},
        )
