from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from app.memory.types import MemoryEntry


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemorySummarizer:
    def summarize(self, entries: list[MemoryEntry], max_items: int = 80) -> str:
        if not entries:
            return "# Memory Summary\n\n(no memory data)\n"

        sample = entries[-max_items:]
        by_type = Counter(item.memory_type.value for item in sample)
        important = sorted(sample, key=lambda item: (item.weight, item.importance), reverse=True)[:8]
        recent = sample[-8:]

        lines: list[str] = []
        lines.append("# Memory Summary")
        lines.append("")
        lines.append(f"Generated at: {_utc_now_iso()}")
        lines.append(f"Total entries: {len(entries)}")
        lines.append("")
        lines.append("## Type Distribution")
        for key, value in sorted(by_type.items(), key=lambda pair: pair[0]):
            lines.append(f"- {key}: {value}")

        lines.append("")
        lines.append("## High-Value Memories")
        for item in important:
            preview = item.content.replace("\n", " ")[:220]
            lines.append(
                f"- [{item.memory_type.value}] importance={item.importance:.2f} "
                f"weight={item.weight:.2f} source={item.source}: {preview}"
            )

        lines.append("")
        lines.append("## Recent Timeline")
        for item in recent:
            preview = item.content.replace("\n", " ")[:220]
            lines.append(
                f"- {item.timestamp.isoformat()} [{item.memory_type.value}] {preview}"
            )

        lines.append("")
        return "\n".join(lines)
