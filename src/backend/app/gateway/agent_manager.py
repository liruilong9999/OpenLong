from __future__ import annotations

from app.agent.runtime import AgentRuntime


class AgentManager:
    def __init__(self, runtime: AgentRuntime) -> None:
        self._runtime = runtime

    def ensure_agent(self, agent_id: str) -> None:
        self._runtime.get_or_create(agent_id)

    def list_agents(self) -> list[str]:
        return self._runtime.list_agents()
