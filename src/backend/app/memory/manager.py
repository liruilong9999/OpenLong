from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.events import EventBus
from app.memory.compressor import MemoryCompressor
from app.memory.retriever import MemoryRetriever
from app.memory.summarizer import MemorySummarizer
from app.memory.types import MemoryEntry, MemoryType
from app.memory.writer import MemoryWriter
from app.workspace.manager import WorkspaceManager


class MemoryManager:
    def __init__(self, workspace_manager: WorkspaceManager, event_bus: EventBus | None = None) -> None:
        self._workspace_manager = workspace_manager
        self._writer = MemoryWriter()
        self._retriever = MemoryRetriever()
        self._compressor = MemoryCompressor()
        self._summarizer = MemorySummarizer()
        self._event_bus = event_bus

    def _memory_paths(self, agent_id: str) -> dict[str, Path]:
        workspace = self._workspace_manager.ensure_agent_workspace(agent_id)
        memory_dir = workspace / "memory"
        logs_dir = memory_dir / "logs"
        summaries_dir = memory_dir / "summaries"

        return {
            "records_file": logs_dir / "memory_records.jsonl",
            "legacy_log_file": logs_dir / "memory.log",
            "summary_file": summaries_dir / "latest.md",
        }

    def _load_entries(self, records_file: Path) -> list[MemoryEntry]:
        if not records_file.exists():
            return []

        entries: list[MemoryEntry] = []
        for line in records_file.read_text(encoding="utf-8").splitlines():
            payload = line.strip()
            if not payload:
                continue

            try:
                data = json.loads(payload)
                entries.append(MemoryEntry.from_dict(data))
            except Exception:
                continue

        entries.sort(key=lambda item: item.timestamp)
        return entries

    def _save_entries(self, records_file: Path, entries: list[MemoryEntry]) -> None:
        self._writer.write_all(records_file, entries)

    def _save_summary(self, summary_file: Path, entries: list[MemoryEntry], max_items: int = 80) -> str:
        summary = self._summarizer.summarize(entries, max_items=max_items)
        summary_file.parent.mkdir(parents=True, exist_ok=True)
        summary_file.write_text(summary, encoding="utf-8")
        return summary

    def _normalize_memory_type(self, memory_type: str | MemoryType | None, content: str) -> MemoryType:
        if isinstance(memory_type, MemoryType):
            return memory_type

        if isinstance(memory_type, str) and memory_type.strip():
            normalized = memory_type.strip().lower()
            for item in MemoryType:
                if item.value == normalized:
                    return item
            return MemoryType.CONVERSATION

        text = content.strip().lower()
        if text.startswith("user_fact:"):
            return MemoryType.USER_INFO
        if text.startswith("user_input:"):
            return MemoryType.CONVERSATION
        if text.startswith("tool_result:"):
            return MemoryType.TOOL_RESULT
        if text.startswith("assistant_output:"):
            return MemoryType.AGENT_SUMMARY
        if text.startswith("task_result:"):
            return MemoryType.TASK_RESULT

        if "用户" in content or "偏好" in content or "name=" in text:
            return MemoryType.USER_INFO
        if "总结" in content or "summary" in text:
            return MemoryType.AGENT_SUMMARY
        if "工具" in content or "tool=" in text:
            return MemoryType.TOOL_RESULT

        return MemoryType.CONVERSATION

    def _infer_importance(self, memory_type: MemoryType, content: str, explicit: float | None) -> float:
        if explicit is not None:
            return max(0.0, min(float(explicit), 1.0))

        defaults = {
            MemoryType.USER_INFO: 0.88,
            MemoryType.TASK_RESULT: 0.75,
            MemoryType.AGENT_SUMMARY: 0.62,
            MemoryType.TOOL_RESULT: 0.68,
            MemoryType.FACT: 0.82,
            MemoryType.CONVERSATION: 0.50,
        }
        score = defaults.get(memory_type, 0.5)

        lowered = content.lower()
        if any(key in content for key in ["重要", "必须", "永远", "关键"]):
            score += 0.1
        if any(key in lowered for key in ["critical", "important", "must", "always"]):
            score += 0.1
        if any(key in lowered for key in ["error", "failed", "失败", "报错"]):
            score += 0.06

        return max(0.0, min(score, 1.0))

    def write(
        self,
        agent_id: str,
        session_id: str,
        entry: str,
        *,
        memory_type: str | MemoryType | None = None,
        importance: float | None = None,
        source: str = "agent",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        paths = self._memory_paths(agent_id)
        entries = self._load_entries(paths["records_file"])

        resolved_type = self._normalize_memory_type(memory_type, entry)
        resolved_importance = self._infer_importance(resolved_type, entry, importance)

        record = MemoryEntry.create(
            memory_type=resolved_type,
            content=entry,
            source=source,
            session_id=session_id,
            importance=resolved_importance,
            metadata=metadata,
        )
        entries.append(record)

        self._retriever.apply_decay(entries)
        entries, removed = self._compressor.compress(entries)

        self._save_entries(paths["records_file"], entries)
        self._writer.append_legacy_line(
            paths["legacy_log_file"],
            (
                f"{record.timestamp.isoformat()} | type={record.memory_type.value} "
                f"importance={record.importance:.2f} source={record.source} "
                f"session={record.session_id} | {record.content}"
            ),
        )
        self._save_summary(paths["summary_file"], entries)

        if self._event_bus is not None:
            self._event_bus.emit(
                "memory.write.completed",
                {
                    "session_id": session_id,
                    "agent_id": agent_id,
                    "entry_size": len(entry),
                    "memory_type": record.memory_type.value,
                    "importance": record.importance,
                    "removed": removed,
                },
            )

        return {
            "memory_id": record.memory_id,
            "memory_type": record.memory_type.value,
            "importance": record.importance,
            "removed": removed,
            "total_entries": len(entries),
        }

    def retrieve(self, agent_id: str, query: str, max_items: int = 8) -> list[str]:
        result = self.query(agent_id=agent_id, query=query, limit=max_items)
        return [f"[{item['memory_type']}] {item['content']}" for item in result["items"]]

    def query(
        self,
        *,
        agent_id: str,
        query: str,
        limit: int = 20,
        memory_type: str | None = None,
        min_weight: float = 0.0,
        similarity_threshold: float = 0.12,
    ) -> dict[str, Any]:
        paths = self._memory_paths(agent_id)
        entries = self._load_entries(paths["records_file"])

        changed = self._retriever.apply_decay(entries)
        matches = self._retriever.search(
            entries,
            query=query,
            limit=limit,
            memory_type=memory_type,
            min_weight=min_weight,
            similarity_threshold=similarity_threshold,
        )

        # 检索会更新 access_count/last_accessed_at，持久化到磁盘。
        if changed or matches:
            self._save_entries(paths["records_file"], entries)

        items = [
            {
                "memory_id": entry.memory_id,
                "timestamp": entry.timestamp.isoformat(),
                "memory_type": entry.memory_type.value,
                "content": entry.content,
                "importance": entry.importance,
                "weight": entry.weight,
                "source": entry.source,
                "session_id": entry.session_id,
                "access_count": entry.access_count,
                "last_accessed_at": entry.last_accessed_at.isoformat() if entry.last_accessed_at else None,
                "metadata": entry.metadata,
                "score": match.score,
                "score_breakdown": match.to_dict(),
            }
            for match in matches
            for entry in [match.entry]
        ]

        return {
            "agent_id": agent_id,
            "query": query,
            "similarity_threshold": similarity_threshold,
            "total_entries": len(entries),
            "matched": len(items),
            "items": items,
        }

    def summarize(self, agent_id: str, max_items: int = 120) -> dict[str, Any]:
        paths = self._memory_paths(agent_id)
        entries = self._load_entries(paths["records_file"])
        summary = self._save_summary(paths["summary_file"], entries, max_items=max_items)

        if self._event_bus is not None:
            self._event_bus.emit(
                "memory.summary.updated",
                {
                    "session_id": "",
                    "agent_id": agent_id,
                    "summary_length": len(summary),
                },
            )

        return {
            "agent_id": agent_id,
            "summary_length": len(summary),
            "entries": len(entries),
        }

    def compress(self, agent_id: str) -> dict[str, Any]:
        paths = self._memory_paths(agent_id)
        entries = self._load_entries(paths["records_file"])
        before = len(entries)

        self._retriever.apply_decay(entries)
        compressed, removed = self._compressor.compress(entries)
        self._save_entries(paths["records_file"], compressed)
        self._save_summary(paths["summary_file"], compressed)

        if self._event_bus is not None:
            self._event_bus.emit(
                "memory.compressed",
                {
                    "session_id": "",
                    "agent_id": agent_id,
                    "before": before,
                    "after": len(compressed),
                    "removed": removed,
                },
            )

        return {
            "agent_id": agent_id,
            "before": before,
            "after": len(compressed),
            "removed": removed,
        }

    def decay(self, agent_id: str) -> dict[str, Any]:
        paths = self._memory_paths(agent_id)
        entries = self._load_entries(paths["records_file"])
        changed = self._retriever.apply_decay(entries)
        if changed:
            self._save_entries(paths["records_file"], entries)

        if self._event_bus is not None:
            self._event_bus.emit(
                "memory.decay.applied",
                {
                    "session_id": "",
                    "agent_id": agent_id,
                    "changed": changed,
                    "entries": len(entries),
                },
            )

        return {
            "agent_id": agent_id,
            "changed": changed,
            "entries": len(entries),
        }

    def get_summary_text(self, agent_id: str) -> str:
        paths = self._memory_paths(agent_id)
        summary_file = paths["summary_file"]
        if summary_file.exists():
            return summary_file.read_text(encoding="utf-8")

        entries = self._load_entries(paths["records_file"])
        return self._save_summary(summary_file, entries)

    def status(self, agent_id: str) -> dict[str, object]:
        paths = self._memory_paths(agent_id)
        entries = self._load_entries(paths["records_file"])
        self._retriever.apply_decay(entries)

        by_type: dict[str, int] = {}
        for item in entries:
            by_type[item.memory_type.value] = by_type.get(item.memory_type.value, 0) + 1

        total_importance = sum(item.importance for item in entries)
        total_weight = sum(item.weight for item in entries)
        avg_importance = total_importance / len(entries) if entries else 0.0
        avg_weight = total_weight / len(entries) if entries else 0.0

        summary_text = self.get_summary_text(agent_id)

        return {
            "agent_id": agent_id,
            "log_file": str(paths["records_file"]),
            "legacy_log_file": str(paths["legacy_log_file"]),
            "summary_file": str(paths["summary_file"]),
            "log_exists": paths["records_file"].exists(),
            "summary_exists": paths["summary_file"].exists(),
            "entries": len(entries),
            "by_type": by_type,
            "avg_importance": round(avg_importance, 6),
            "avg_weight": round(avg_weight, 6),
            "log_size_bytes": paths["records_file"].stat().st_size if paths["records_file"].exists() else 0,
            "summary_size_bytes": paths["summary_file"].stat().st_size if paths["summary_file"].exists() else 0,
            "summary_preview": summary_text[:1200],
        }
