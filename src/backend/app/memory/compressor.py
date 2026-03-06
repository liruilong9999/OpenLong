from __future__ import annotations

from pathlib import Path


class MemoryCompressor:
    def compress(self, source_log: Path, summary_file: Path, max_lines: int = 30) -> None:
        if not source_log.exists():
            return

        lines = source_log.read_text(encoding="utf-8").splitlines()[-max_lines:]
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        summary_file.write_text("\n".join(lines), encoding="utf-8")
