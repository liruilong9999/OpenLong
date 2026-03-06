from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from app.memory.types import MemoryEntry


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]+")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryRetriever:
    def apply_decay(
        self,
        entries: list[MemoryEntry],
        *,
        now: datetime | None = None,
        low_importance_half_life_hours: float = 72.0,
        high_importance_half_life_hours: float = 336.0,
        min_weight: float = 0.03,
    ) -> bool:
        changed = False
        current = now or _utc_now()

        for entry in entries:
            age_hours = max((current - entry.timestamp).total_seconds() / 3600.0, 0.0)
            half_life = (
                high_importance_half_life_hours
                if entry.importance >= 0.7
                else low_importance_half_life_hours
            )
            decay_factor = math.pow(0.5, age_hours / max(half_life, 1.0))
            new_weight = max(entry.importance * decay_factor, min_weight)

            if abs(new_weight - entry.weight) > 1e-6:
                entry.weight = round(new_weight, 6)
                changed = True

        return changed

    def search(
        self,
        entries: list[MemoryEntry],
        *,
        query: str,
        limit: int = 8,
        memory_type: str | None = None,
        min_weight: float = 0.0,
    ) -> list[tuple[MemoryEntry, float]]:
        query_tokens = self._tokenize(query)
        now = _utc_now()

        candidates: list[tuple[MemoryEntry, float]] = []
        for entry in entries:
            if memory_type and entry.memory_type.value != memory_type:
                continue
            if entry.weight < min_weight:
                continue

            score = self._score_entry(entry=entry, query_tokens=query_tokens, now=now)
            candidates.append((entry, score))

        candidates.sort(key=lambda item: item[1], reverse=True)
        selected = candidates[: max(limit, 0)]

        for entry, _ in selected:
            entry.access_count += 1
            entry.last_accessed_at = now

        return selected

    def _score_entry(self, *, entry: MemoryEntry, query_tokens: set[str], now: datetime) -> float:
        content_tokens = self._tokenize(entry.content)
        overlap_ratio = 0.0
        if query_tokens:
            overlap = len(query_tokens.intersection(content_tokens))
            overlap_ratio = overlap / max(len(query_tokens), 1)

        age_hours = max((now - entry.timestamp).total_seconds() / 3600.0, 0.0)
        recency_bonus = max(0.0, 1.0 - (age_hours / 720.0))
        access_bonus = min(entry.access_count, 20) / 100.0

        return (overlap_ratio * 0.55) + (entry.weight * 0.30) + (recency_bonus * 0.10) + (access_bonus * 0.05)

    def _tokenize(self, text: str) -> set[str]:
        return {token.lower() for token in _TOKEN_PATTERN.findall(text or "")}
