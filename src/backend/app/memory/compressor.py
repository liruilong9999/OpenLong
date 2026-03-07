from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any

from app.memory.summarizer import MemorySummarizer
from app.memory.types import MemoryEntry, MemoryType


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]+")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def estimate_text_tokens(text: str) -> int:
    normalized = str(text or "")
    lexical = len(_TOKEN_PATTERN.findall(normalized))
    heuristic = math.ceil(len(normalized) / 4)
    return max(1, lexical, heuristic)


class MemoryCompressor:
    def __init__(self) -> None:
        self._summarizer = MemorySummarizer()

    def compress(
        self,
        entries: list[MemoryEntry],
        *,
        max_entries: int = 1200,
        max_total_chars: int = 300000,
        max_total_tokens: int = 60000,
        keep_recent: int = 120,
        preserve_high_priority: int = 32,
    ) -> tuple[list[MemoryEntry], int]:
        if not entries:
            return entries, 0

        ordered = sorted(entries, key=lambda item: item.timestamp)
        removed = 0
        total_chars = self.estimate_total_chars(ordered)
        total_tokens = self.estimate_total_tokens(ordered)
        if len(ordered) <= max_entries and total_chars <= max_total_chars and total_tokens <= max_total_tokens:
            return ordered, 0

        protected_ids = self._protected_ids(
            ordered,
            keep_recent=min(max(keep_recent, 0), max(max_entries - 1, 1), len(ordered)),
            preserve_high_priority=preserve_high_priority,
            max_entries=max_entries,
        )
        candidates = [item for item in ordered if item.memory_id not in protected_ids]

        if candidates:
            summary_candidates = self._select_summary_candidates(
                ordered,
                candidates,
                max_entries=max_entries,
                max_total_chars=max_total_chars,
                max_total_tokens=max_total_tokens,
            )
            if summary_candidates:
                summary_entry = self._build_summary_entry(summary_candidates)
                summary_ids = {item.memory_id for item in summary_candidates}
                ordered = [item for item in ordered if item.memory_id not in summary_ids]
                ordered.append(summary_entry)
                ordered.sort(key=lambda item: item.timestamp)
                removed += len(summary_candidates) - 1
                total_chars = self.estimate_total_chars(ordered)
                total_tokens = self.estimate_total_tokens(ordered)

        if len(ordered) > max_entries or total_chars > max_total_chars or total_tokens > max_total_tokens:
            ordered, extra_removed = self._trim_residual(
                ordered,
                max_entries=max_entries,
                max_total_chars=max_total_chars,
                max_total_tokens=max_total_tokens,
                keep_recent=keep_recent,
            )
            removed += extra_removed

        return ordered, removed

    def estimate_total_chars(self, entries: list[MemoryEntry]) -> int:
        return sum(len(item.content) for item in entries)

    def estimate_total_tokens(self, entries: list[MemoryEntry]) -> int:
        return sum(estimate_text_tokens(item.content) for item in entries)

    def _protected_ids(
        self,
        entries: list[MemoryEntry],
        *,
        keep_recent: int,
        preserve_high_priority: int,
        max_entries: int,
    ) -> set[str]:
        protected: set[str] = set()
        protected.update(item.memory_id for item in entries[-max(keep_recent, 0):])

        important = sorted(
            entries,
            key=lambda item: (self._is_priority_fact(item), item.importance, item.weight, item.access_count),
            reverse=True,
        )
        priority_limit = min(max(preserve_high_priority, 0), max(1, max_entries // 2))
        for item in important[:priority_limit]:
            if self._is_priority_fact(item):
                protected.add(item.memory_id)
        return protected

    def _select_summary_candidates(
        self,
        ordered: list[MemoryEntry],
        candidates: list[MemoryEntry],
        *,
        max_entries: int,
        max_total_chars: int,
        max_total_tokens: int,
    ) -> list[MemoryEntry]:
        current_chars = self.estimate_total_chars(ordered)
        current_tokens = self.estimate_total_tokens(ordered)
        overflow_entries = max(len(ordered) - max_entries, 0)
        overflow_chars = max(current_chars - max_total_chars, 0)
        overflow_tokens = max(current_tokens - max_total_tokens, 0)

        selected: list[MemoryEntry] = []
        saved_entries = 0
        saved_chars = 0
        saved_tokens = 0

        for item in sorted(candidates, key=lambda entry: (entry.timestamp, self._retention_score(entry))):
            selected.append(item)
            saved_entries += 1
            saved_chars += len(item.content)
            saved_tokens += estimate_text_tokens(item.content)
            if (
                saved_entries >= max(overflow_entries + 1, 2)
                or saved_chars >= overflow_chars * 1.10
                or saved_tokens >= overflow_tokens * 1.10
            ):
                break

        return selected

    def _build_summary_entry(self, entries: list[MemoryEntry]) -> MemoryEntry:
        summary = self._summarizer.summarize_compaction(entries)
        importance = min(0.96, max(0.72, max(item.importance for item in entries)))
        session_id = entries[-1].session_id if entries else ""
        summary_entry = MemoryEntry.create(
            memory_type=MemoryType.AGENT_SUMMARY,
            content=summary,
            source="memory_compactor",
            session_id=session_id,
            importance=importance,
            metadata={
                "compaction": True,
                "compressed_count": len(entries),
                "source_ids": [item.memory_id for item in entries[:20]],
                "time_range": {
                    "start": entries[0].timestamp.isoformat(),
                    "end": entries[-1].timestamp.isoformat(),
                },
            },
        )
        summary_entry.timestamp = entries[-1].timestamp
        summary_entry.weight = max(summary_entry.weight, 0.68)
        return summary_entry

    def _trim_residual(
        self,
        entries: list[MemoryEntry],
        *,
        max_entries: int,
        max_total_chars: int,
        max_total_tokens: int,
        keep_recent: int,
    ) -> tuple[list[MemoryEntry], int]:
        ordered = list(entries)
        keep_ids = {item.memory_id for item in ordered[-max(keep_recent, 0):]}
        keep_ids.update(
            item.memory_id
            for item in ordered
            if item.memory_type == MemoryType.AGENT_SUMMARY and item.metadata.get("compaction")
        )
        removed = 0

        while (
            len(ordered) > max_entries
            or self.estimate_total_chars(ordered) > max_total_chars
            or self.estimate_total_tokens(ordered) > max_total_tokens
        ):
            removable = [item for item in ordered if item.memory_id not in keep_ids]
            if not removable:
                break
            candidate = min(removable, key=self._retention_score)
            ordered.remove(candidate)
            removed += 1

        ordered.sort(key=lambda item: item.timestamp)
        return ordered, removed

    def _retention_score(self, entry: MemoryEntry) -> float:
        now = _utc_now()
        age_hours = max((now - entry.timestamp).total_seconds() / 3600.0, 0.0)
        recency = max(0.0, 1.0 - age_hours / 1440.0)
        access_bonus = min(entry.access_count, 25) / 50.0
        summary_penalty = 0.06 if entry.memory_type == MemoryType.AGENT_SUMMARY else 0.0
        return (entry.weight * 0.50) + (entry.importance * 0.23) + (recency * 0.15) + (access_bonus * 0.06) + (summary_penalty)

    def _is_priority_fact(self, entry: MemoryEntry) -> bool:
        if entry.memory_type in {MemoryType.USER_INFO, MemoryType.FACT} and max(entry.importance, entry.weight) >= 0.78:
            return True
        if entry.importance >= 0.9:
            return True
        lowered = entry.content.lower()
        return any(token in lowered for token in ["must", "always", "关键", "重要", "name="])
