from __future__ import annotations

from pathlib import Path

from app.memory.compressor import MemoryCompressor
from app.memory.retriever import MemoryRetriever
from app.memory.writer import MemoryWriter
from app.workspace.manager import WorkspaceManager


class MemoryManager:
    def __init__(self, workspace_manager: WorkspaceManager) -> None:
        self._workspace_manager = workspace_manager
        self._writer = MemoryWriter()
        self._retriever = MemoryRetriever()
        self._compressor = MemoryCompressor()

    def _memory_paths(self, agent_id: str) -> tuple[Path, Path]:
        workspace = self._workspace_manager.ensure_agent_workspace(agent_id)
        memory_dir = workspace / "memory"
        return memory_dir / "logs" / "memory.log", memory_dir / "summaries" / "latest.md"

    def write(self, agent_id: str, session_id: str, entry: str) -> None:
        log_file, summary_file = self._memory_paths(agent_id)
        self._writer.write(log_file, f"session={session_id} | {entry}")
        self._compressor.compress(log_file, summary_file)

    def retrieve(self, agent_id: str, query: str, max_items: int = 8) -> list[str]:
        del query
        log_file, _ = self._memory_paths(agent_id)
        return self._retriever.retrieve_recent(log_file, max_items=max_items)
