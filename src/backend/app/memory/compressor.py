from __future__ import annotations

from datetime import datetime, timezone

from app.memory.types import MemoryEntry


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryCompressor:
    def compress(
        self,
        entries: list[MemoryEntry],
        *,
        max_entries: int = 1200,
        max_total_chars: int = 300000,
        keep_recent: int = 120,
    ) -> tuple[list[MemoryEntry], int]:
        if not entries:
            return entries, 0

        ordered = sorted(entries, key=lambda item: item.timestamp)
        removed = 0
        recent_keep = min(max(keep_recent, 0), max(max_entries, 0), len(ordered))

        if len(ordered) > max_entries:
            protected = ordered[-recent_keep:] if recent_keep > 0 else []
            protected_ids = {item.memory_id for item in protected}
            pool = [item for item in ordered if item.memory_id not in protected_ids]

            pool.sort(key=lambda item: self._retention_score(item), reverse=True)
            keep_needed = max(max_entries - len(protected), 0)
            selected = pool[:keep_needed] + protected
            selected.sort(key=lambda item: item.timestamp)
            removed += len(ordered) - len(selected)
            ordered = selected

        total_chars = sum(len(item.content) for item in ordered)
        if total_chars > max_total_chars:
            scored = sorted(ordered, key=lambda item: self._retention_score(item))
            keep_ids = {item.memory_id for item in ordered[-recent_keep:]} if recent_keep > 0 else set()

            while total_chars > max_total_chars and scored:
                candidate = scored.pop(0)
                if candidate.memory_id in keep_ids:
                    continue
                if candidate in ordered:
                    ordered.remove(candidate)
                    total_chars -= len(candidate.content)
                    removed += 1

        return ordered, removed

    def _retention_score(self, entry: MemoryEntry) -> float:
        now = _utc_now()
        age_hours = max((now - entry.timestamp).total_seconds() / 3600.0, 0.0)
        recency = max(0.0, 1.0 - age_hours / 1440.0)
        access_bonus = min(entry.access_count, 25) / 50.0
        return (entry.weight * 0.55) + (entry.importance * 0.25) + (recency * 0.15) + (access_bonus * 0.05)
