from __future__ import annotations

from app.models.message import ChatMessage


class PromptBuilder:
    def build(
        self,
        context_block: str,
        history: list[ChatMessage],
        memories: list[str],
        skills: list[str],
        user_message: str,
    ) -> str:
        history_text = "\n".join(msg.to_prompt_line() for msg in history[-12:])
        memory_text = "\n".join(f"- {item}" for item in memories)
        skills_text = "\n".join(f"- {name}" for name in skills)

        return (
            f"[CONTEXT]\n{context_block}\n\n"
            f"[SKILLS]\n{skills_text or '- none'}\n\n"
            f"[MEMORY]\n{memory_text or '- none'}\n\n"
            f"[HISTORY]\n{history_text or '- none'}\n\n"
            f"[USER]\n{user_message}"
        )
