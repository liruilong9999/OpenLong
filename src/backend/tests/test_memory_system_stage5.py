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

    compressed, removed = compressor.compress(entries, max_entries=8, max_total_chars=500, max_total_tokens=160)
    assert len(compressed) <= 8
    assert removed > 0
    assert any(item.memory_type == MemoryType.AGENT_SUMMARY for item in compressed)


def test_memory_compaction_preserves_historical_recall_via_summary(tmp_path: Path) -> None:
    workspace_manager = WorkspaceManager(str(tmp_path))
    manager = MemoryManager(workspace_manager)

    for index in range(25):
        manager.write(
            agent_id="main",
            session_id=f"hist-{index}",
            entry=f"user_fact: Alice likes Python and testing workflows #{index}",
            source="history_test",
            memory_type="user_info",
            importance=0.92 if index == 0 else 0.62,
        )

    paths = manager._memory_paths("main")  # noqa: SLF001
    entries = manager._load_entries(paths["records_file"])  # noqa: SLF001
    compressed, removed = manager._compressor.compress(  # noqa: SLF001
        entries,
        max_entries=8,
        max_total_chars=800,
        max_total_tokens=180,
        keep_recent=4,
    )
    assert removed > 0
    assert any(item.memory_type == MemoryType.AGENT_SUMMARY and item.metadata.get("compaction") for item in compressed)

    manager._save_entries(paths["records_file"], compressed)  # noqa: SLF001

    recalled = manager.query(agent_id="main", query="What does Alice prefer in Python workflows?", limit=5)
    assert recalled["matched"] >= 1
    assert any("Alice" in item["content"] for item in recalled["items"])
    assert any(item["memory_type"] == "agent_summary" for item in recalled["items"])


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


def test_memory_hybrid_semantic_retrieval_handles_synonyms(tmp_path: Path) -> None:
    workspace_manager = WorkspaceManager(str(tmp_path))
    manager = MemoryManager(workspace_manager)

    manager.write(
        agent_id="main",
        session_id="s-sem-1",
        entry="user_fact: 用户喜欢 Python，并且偏好简洁回复",
        source="semantic_test",
        memory_type="user_info",
        importance=0.95,
    )
    manager.write(
        agent_id="main",
        session_id="s-sem-2",
        entry="task_result: 已修复前端页面的报错问题",
        source="semantic_test",
        memory_type="task_result",
        importance=0.8,
    )

    query = manager.query(agent_id="main", query="用户的 py 偏好是什么", limit=5)
    assert query["matched"] >= 1
    first = query["items"][0]
    assert "Python" in first["content"]
    assert first["score_breakdown"]["semantic_score"] > 0
    assert first["score_breakdown"]["lexical_score"] > 0

    bug_query = manager.query(agent_id="main", query="frontend bug", limit=5)
    assert bug_query["matched"] >= 1
    assert "前端页面的报错" in bug_query["items"][0]["content"]


def test_memory_similarity_threshold_filters_irrelevant_results(tmp_path: Path) -> None:
    workspace_manager = WorkspaceManager(str(tmp_path))
    manager = MemoryManager(workspace_manager)

    manager.write(
        agent_id="main",
        session_id="s-threshold",
        entry="user_fact: 用户喜欢 Python",
        source="semantic_test",
        memory_type="user_info",
        importance=0.9,
    )

    relevant = manager.query(agent_id="main", query="python preference", limit=5, similarity_threshold=0.1)
    assert relevant["matched"] >= 1

    irrelevant = manager.query(agent_id="main", query="weather in tokyo", limit=5, similarity_threshold=0.2)
    assert irrelevant["matched"] == 0
