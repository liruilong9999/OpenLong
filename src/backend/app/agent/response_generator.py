from __future__ import annotations


class ResponseGenerator:
    def generate(self, user_message: str, tool_outputs: list[str]) -> str:
        if tool_outputs:
            output = "\n".join(tool_outputs)
            return f"Tool execution completed.\n{output}"

        return (
            "Scaffold runtime active. "
            f"Received: {user_message}. "
            "LLM integration can be plugged into AgentLoop next."
        )
