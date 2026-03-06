from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Any

from app.tools.types import ToolExecutionRecord


class ToolExecutionLogStore:
    def __init__(self, max_records: int = 5000) -> None:
        self._records: deque[ToolExecutionRecord] = deque(maxlen=max_records)
        self._lock = Lock()

    def append(self, record: ToolExecutionRecord) -> None:
        with self._lock:
            self._records.append(record)

    def recent(self, limit: int = 100, tool_name: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            records = list(self._records)

        if tool_name:
            target = tool_name.strip().lower()
            records = [item for item in records if item.tool_name.lower() == target]

        return [item.to_dict() for item in records[-limit:]][::-1]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            records = list(self._records)

        total = len(records)
        success = sum(1 for item in records if item.success)
        denied = sum(1 for item in records if item.denied_reason)
        failed = total - success

        by_tool: dict[str, int] = {}
        for item in records:
            by_tool[item.tool_name] = by_tool.get(item.tool_name, 0) + 1

        return {
            "total": total,
            "success": success,
            "failed": failed,
            "denied": denied,
            "by_tool": by_tool,
        }
