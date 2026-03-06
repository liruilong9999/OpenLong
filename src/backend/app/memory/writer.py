from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


class MemoryWriter:
    def write(self, log_file: Path, entry: str) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(f"{timestamp} | {entry}\n")
