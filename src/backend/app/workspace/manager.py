from __future__ import annotations

from pathlib import Path

from app.context.manager import ContextManager


CONTEXT_DEFAULTS = {
    "USER.md": "# USER\nDescribe user profile and preferences.",
    "SOUL.md": "# SOUL\nDescribe agent personality and behavior.",
    "IDENTITY.md": "# IDENTITY\nDescribe agent role and scope.",
    "RULES.md": "# RULES\nList non-negotiable rules.",
    "STYLE.md": "# STYLE\nDefine response style and format.",
    "MEMORY.md": "# MEMORY\nPersistent memory index for this agent.",
}


class WorkspaceManager:
    def __init__(self, workspace_root: str) -> None:
        repo_root = Path(__file__).resolve().parents[4]
        self._workspace_root = (repo_root / workspace_root).resolve()

    def ensure_agent_workspace(self, agent_id: str) -> Path:
        workspace = self._workspace_root / agent_id
        workspace.mkdir(parents=True, exist_ok=True)

        # 预创建运行所需目录，包含未来的 channel 与自我迭代扩展位。
        for relative_dir in [
            "skills",
            "memory/logs",
            "memory/summaries",
            "logs",
            "channels",
            "self_evolution",
        ]:
            (workspace / relative_dir).mkdir(parents=True, exist_ok=True)

        # 初始化上下文文件，避免首次运行读取失败。
        for filename, content in CONTEXT_DEFAULTS.items():
            path = workspace / filename
            if not path.exists():
                path.write_text(content + "\n", encoding="utf-8")

        return workspace

    def load_context_block(self, agent_id: str) -> str:
        workspace = self.ensure_agent_workspace(agent_id)
        return ContextManager(workspace).build_context()
