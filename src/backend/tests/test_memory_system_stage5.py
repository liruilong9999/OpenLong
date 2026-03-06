from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.memory.compressor import MemoryCompressor
from app.memory.manager import MemoryManager
from app.memory.retriever import MemoryRetriever
from app.memory.types import MemoryEntry, MemoryType
from app.workspace.manager import WorkspaceManager


def test_memory_structure_writer_and_retriever(tmp_path: Path) -> None:
    workspace_manager = WorkspaceManager(str(tmp_path))
    manager = MemoryManager(workspace_manager)

    manager.write(
        agent_id="main",
        session_id="s1",
        entry="user_fact: name=Alice",
        source="agent_runtime",
    )
    manager.write(
        agent_id="main",
        session_id="s1",
        entry="task_result: 已完成阶段5实现",
        source="agent_runtime",
        importance=0.8,
    )

    status = manager.status("main")
    assert status["entries"] >= 2
    assert "by_type" in status

    queried = manager.query(agent_id="main", query="Alice", limit=5)
    assert queried["matched"] >= 1
    first = queried["items"][0]
    assert "timestamp" in first
    assert "memory_type" in first
    assert "importance" in first
    assert "source" in first
    assert "weight" in first

    prompt_memories = manager.retrieve(agent_id="main", query="Alice", max_items=3)
    assert prompt_memories


def test_memory_summarizer_compressor_and_decay() -> None:
    retriever = MemoryRetriever()
    compressor = MemoryCompressor()

    entries: list[MemoryEntry] = []
    for i in range(20):
        item = MemoryEntry.create(
            memory_type=MemoryType.CONVERSATION,
            content=("x" * 80) + f"-{i}",
            source="test",
            session_id="demo",
            importance=0.2 if i < 15 else 0.9,
        )
        if i < 15:
            item.timestamp = item.timestamp - timedelta(days=30)
        entries.append(item)

    changed = retriever.apply_decay(entries)
    assert changed is True
    assert any(item.weight < item.importance for item in entries[:10])

    compressed, removed = compressor.compress(entries, max_entries=8, max_total_chars=500)
    assert len(compressed) <= 8
    assert removed > 0


def test_memory_api_query_and_dashboard() -> None:
    client = TestClient(create_app())

    write_resp = client.post(
        "/tasks/memory",
        json={
            "session_id": "mem-api-s1",
            "agent_id": "main",
            "entry": "user_fact: preference=python",
            "memory_type": "user_info",
            "importance": 0.9,
            "source": "api_test",
            "metadata": {"case": "stage5"},
        },
    )
    assert write_resp.status_code == 200
    assert write_resp.json()["success"] is True

    query_resp = client.get("/memory/main/query", params={"query": "python", "limit": 5})
    assert query_resp.status_code == 200
    payload = query_resp.json()
    assert payload["matched"] >= 1
    assert payload["items"][0]["memory_type"]

    summarize_resp = client.post("/memory/main/summarize")
    assert summarize_resp.status_code == 200

    decay_resp = client.post("/memory/main/decay")
    assert decay_resp.status_code == 200

    compress_resp = client.post("/memory/main/compress")
    assert compress_resp.status_code == 200

    dashboard_resp = client.get("/dashboard/memory/main")
    assert dashboard_resp.status_code == 200
    dash = dashboard_resp.json()
    assert "entries" in dash
    assert "recent_items" in dash
