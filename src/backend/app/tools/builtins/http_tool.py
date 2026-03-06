from __future__ import annotations

from typing import Any

import httpx

from app.tools.types import ToolResult


class HttpTool:
    name = "http"

    async def run(self, **kwargs: Any) -> ToolResult:
        method = str(kwargs.get("method", "GET")).upper()
        url = str(kwargs.get("url", "")).strip()

        if not url:
            return ToolResult(success=False, content="missing url")

        timeout = float(kwargs.get("timeout", 20.0))
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method=method, url=url)
        snippet = response.text[:1000]

        return ToolResult(
            success=response.is_success,
            content=f"status={response.status_code}\n{snippet}",
            data={"status_code": response.status_code},
        )
