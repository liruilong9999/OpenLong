from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import math
import re

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

    def summarize_compaction(self, entries: list[MemoryEntry], max_items: int = 48, max_chars: int = 2400) -> str:
        if not entries:
            return "历史记忆压缩摘要为空。"

        sample = sorted(entries, key=lambda item: item.timestamp)
        selected = sample[:max_items]
        by_type = Counter(item.memory_type.value for item in selected)
        important = sorted(selected, key=lambda item: (item.importance, item.weight, item.access_count), reverse=True)[:10]
        keywords = self._keywords(selected, limit=8)

        lines: list[str] = []
        lines.append(f"历史摘要：覆盖 {len(entries)} 条旧记忆。")
        lines.append(
            f"时间范围：{selected[0].timestamp.isoformat()} ~ {selected[-1].timestamp.isoformat()}。"
        )
        lines.append("类型分布：" + ", ".join(f"{key}={value}" for key, value in sorted(by_type.items())))
        if keywords:
            lines.append("主题关键词：" + "、".join(keywords))
        lines.append("关键事实：")
        for item in important:
            preview = self._preview(item.content, 160)
            lines.append(f"- [{item.memory_type.value}] {preview}")

        text = "\n".join(lines)
        if len(text) <= max_chars:
            return text

        overflow = len(text) - max_chars
        trim_ratio = max(0.45, 1.0 - (overflow / max(len(text), 1)))
        reduced: list[str] = lines[:4]
        for item in important:
            preview = self._preview(item.content, max(60, math.floor(140 * trim_ratio)))
            reduced.append(f"- [{item.memory_type.value}] {preview}")
            compact = "\n".join(reduced)
            if len(compact) >= max_chars:
                break
        return "\n".join(reduced)[:max_chars].rstrip()

    def _keywords(self, entries: list[MemoryEntry], limit: int = 8) -> list[str]:
        token_pattern = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}")
        noise = {"user_fact", "task_result", "tool_result", "assistant_output", "用户", "喜欢", "请", "以及", "然后", "已经", "当前"}
        counter: Counter[str] = Counter()
        for item in entries:
            for token in token_pattern.findall(item.content or ""):
                normalized = token.lower()
                if normalized in noise:
                    continue
                counter[normalized] += 1
        return [item for item, _ in counter.most_common(limit)]

    def _preview(self, text: str, limit: int) -> str:
        normalized = re.sub(r"\s+", " ", text or "").strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[: max(limit - 1, 1)] + "…"
