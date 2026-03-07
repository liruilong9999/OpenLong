from __future__ import annotations

from dataclasses import dataclass
import math
import re
from datetime import datetime, timezone
from typing import Any

from app.memory.types import MemoryEntry


_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]+")
_CJK_PATTERN = re.compile(r"[\u4e00-\u9fff]+")

_SEMANTIC_GROUPS = [
    {"python", "python3", "py"},
    {"偏好", "喜欢", "喜好", "preference", "prefer", "prefers", "like", "likes"},
    {"代码", "编码", "coding", "code", "programming"},
    {"前端", "frontend", "ui", "web", "网页", "页面"},
    {"后端", "backend", "server", "服务端", "api"},
    {"错误", "异常", "报错", "bug", "error", "issue", "failed", "failure"},
    {"总结", "摘要", "summary", "summarize", "recap"},
    {"项目", "工程", "仓库", "repo", "repository", "project"},
    {"运行", "执行", "run", "execute"},
    {"记忆", "memory", "回忆", "recall"},
    {"测试", "test", "pytest", "spec"},
]

_SEMANTIC_ALIAS_MAP: dict[str, set[str]] = {}
for group in _SEMANTIC_GROUPS:
    normalized_group = {item.lower() for item in group}
    for item in normalized_group:
        _SEMANTIC_ALIAS_MAP[item] = normalized_group


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class SearchMatch:
    entry: MemoryEntry
    score: float
    lexical_score: float
    semantic_score: float
    weight_score: float
    recency_score: float
    access_score: float
    fusion_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "lexical_score": self.lexical_score,
            "semantic_score": self.semantic_score,
            "weight_score": self.weight_score,
            "recency_score": self.recency_score,
            "access_score": self.access_score,
            "fusion_score": self.fusion_score,
        }


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
        similarity_threshold: float = 0.12,
    ) -> list[SearchMatch]:
        query_tokens = self._tokenize(query)
        query_vector = self._semantic_embedding(query)
        now = _utc_now()

        candidates: list[dict[str, Any]] = []
        for entry in entries:
            if memory_type and entry.memory_type.value != memory_type:
                continue
            if entry.weight < min_weight:
                continue

            row = self._score_entry(
                entry=entry,
                query_tokens=query_tokens,
                query_vector=query_vector,
                now=now,
            )
            row["entry"] = entry
            candidates.append(row)

        if not candidates:
            return []

        lexical_sorted = sorted(candidates, key=lambda item: item["lexical_score"], reverse=True)
        semantic_sorted = sorted(candidates, key=lambda item: item["semantic_score"], reverse=True)
        lexical_ranks = {id(item["entry"]): index + 1 for index, item in enumerate(lexical_sorted)}
        semantic_ranks = {id(item["entry"]): index + 1 for index, item in enumerate(semantic_sorted)}

        matches: list[SearchMatch] = []
        for item in candidates:
            entry = item["entry"]
            fusion_score = self._fusion_score(
                lexical_rank=lexical_ranks[id(entry)],
                semantic_rank=semantic_ranks[id(entry)],
            )
            final_score = (
                item["lexical_score"] * 0.30
                + item["semantic_score"] * 0.30
                + item["weight_score"] * 0.20
                + item["recency_score"] * 0.12
                + item["access_score"] * 0.03
                + fusion_score * 0.05
            )

            if query.strip() and max(item["lexical_score"], item["semantic_score"]) < similarity_threshold:
                continue

            matches.append(
                SearchMatch(
                    entry=entry,
                    score=round(final_score, 6),
                    lexical_score=round(item["lexical_score"], 6),
                    semantic_score=round(item["semantic_score"], 6),
                    weight_score=round(item["weight_score"], 6),
                    recency_score=round(item["recency_score"], 6),
                    access_score=round(item["access_score"], 6),
                    fusion_score=round(fusion_score, 6),
                )
            )

        matches.sort(key=lambda item: item.score, reverse=True)
        selected = matches[: max(limit, 0)]

        for item in selected:
            item.entry.access_count += 1
            item.entry.last_accessed_at = now

        return selected

    def _score_entry(
        self,
        *,
        entry: MemoryEntry,
        query_tokens: set[str],
        query_vector: dict[str, float],
        now: datetime,
    ) -> dict[str, float]:
        content_tokens = self._tokenize(entry.content)
        lexical_score = 0.0
        if query_tokens:
            overlap = len(query_tokens.intersection(content_tokens))
            lexical_score = overlap / max(len(query_tokens), 1)

        content_vector = self._semantic_embedding(entry.content)
        semantic_score = self._cosine_similarity(query_vector, content_vector) if query_vector else 0.0

        age_hours = max((now - entry.timestamp).total_seconds() / 3600.0, 0.0)
        recency_score = max(0.0, 1.0 - (age_hours / 720.0))
        access_score = min(entry.access_count, 20) / 100.0

        return {
            "lexical_score": lexical_score,
            "semantic_score": semantic_score,
            "weight_score": entry.weight,
            "recency_score": recency_score,
            "access_score": access_score,
        }

    def _semantic_embedding(self, text: str) -> dict[str, float]:
        tokens = self._tokenize(text)
        if not tokens:
            return {}

        vector: dict[str, float] = {}
        for token in tokens:
            self._bump(vector, f"tok:{token}", 1.0)
            aliases = _SEMANTIC_ALIAS_MAP.get(token, {token})
            canonical = sorted(aliases)[0]
            self._bump(vector, f"alias:{canonical}", 0.8)

        compact = " ".join(tokens)
        for gram in self._character_ngrams(compact):
            self._bump(vector, f"gram:{gram}", 0.35)

        self._normalize_vector(vector)
        return vector

    def _tokenize(self, text: str) -> set[str]:
        tokens = {token.lower() for token in _TOKEN_PATTERN.findall(text or "")}
        enriched: set[str] = set(tokens)
        for token in list(tokens):
            if _CJK_PATTERN.search(token):
                enriched.update(self._character_ngrams(token, min_size=2, max_size=3))
                for alias_key, alias_group in _SEMANTIC_ALIAS_MAP.items():
                    if alias_key in token:
                        enriched.update(alias_group)
            elif len(token) > 3:
                for alias_key, alias_group in _SEMANTIC_ALIAS_MAP.items():
                    if alias_key in token:
                        enriched.update(alias_group)

        tokens = enriched
        expanded: set[str] = set(tokens)
        for token in list(tokens):
            expanded.update(_SEMANTIC_ALIAS_MAP.get(token, {token}))
        return expanded

    def _character_ngrams(self, text: str, min_size: int = 2, max_size: int = 3) -> set[str]:
        compact = re.sub(r"\s+", "", text or "")
        if len(compact) < min_size:
            return {compact} if compact else set()

        grams: set[str] = set()
        for size in range(min_size, max_size + 1):
            if len(compact) < size:
                continue
            for index in range(len(compact) - size + 1):
                piece = compact[index : index + size]
                if _CJK_PATTERN.fullmatch(piece) or piece.isalnum():
                    grams.add(piece.lower())
        return grams

    def _cosine_similarity(self, left: dict[str, float], right: dict[str, float]) -> float:
        if not left or not right:
            return 0.0
        overlap = set(left).intersection(right)
        if not overlap:
            return 0.0
        return max(0.0, min(sum(left[key] * right[key] for key in overlap), 1.0))

    def _fusion_score(self, *, lexical_rank: int, semantic_rank: int, k: int = 60) -> float:
        return (1.0 / (k + lexical_rank)) + (1.0 / (k + semantic_rank))

    def _bump(self, vector: dict[str, float], key: str, value: float) -> None:
        vector[key] = vector.get(key, 0.0) + value

    def _normalize_vector(self, vector: dict[str, float]) -> None:
        norm = math.sqrt(sum(value * value for value in vector.values()))
        if norm <= 0:
            return
        for key in list(vector.keys()):
            vector[key] = vector[key] / norm
