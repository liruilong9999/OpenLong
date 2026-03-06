from __future__ import annotations

from collections import deque
from pathlib import Path


class MemoryRetriever:
    def retrieve_recent(self, log_file: Path, max_items: int = 8) -> list[str]:
        if not log_file.exists():
            return []

        last_lines: deque[str] = deque(maxlen=max_items)
        with log_file.open("r", encoding="utf-8") as fh:
            for line in fh:
                last_lines.append(line.strip())
        return list(last_lines)
