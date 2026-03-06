from __future__ import annotations

import json
from pathlib import Path

from app.memory.types import MemoryEntry


class MemoryWriter:
    def write_all(self, records_file: Path, entries: list[MemoryEntry]) -> None:
        records_file.parent.mkdir(parents=True, exist_ok=True)
        with records_file.open("w", encoding="utf-8") as fh:
            for entry in entries:
                fh.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    def append_legacy_line(self, log_file: Path, text: str) -> None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(text.rstrip() + "\n")
