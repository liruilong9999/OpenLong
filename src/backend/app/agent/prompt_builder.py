from __future__ import annotations

from dataclasses import dataclass

from app.models.message import ChatMessage
from app.skills.types import SkillSpec


@dataclass(slots=True)
class PromptBundle:
    context_block: str
    memory_block: str
    skill_block: str
    history_block: str
    scratchpad_block: str
    user_block: str
    full_prompt: str


class PromptBuilder:
    def build(
        self,
        context_block: str,
        history: list[ChatMessage],
        memories: list[str],
        skills: list[SkillSpec],
        matched_skills: list[SkillSpec],
        user_message: str,
        scratchpad: str = "",
    ) -> PromptBundle:
        history_text = "\n".join(msg.to_prompt_line() for msg in history[-16:])
        memory_text = "\n".join(f"- {item}" for item in memories)

        available_skills = "\n".join(f"- {skill.prompt_view()}" for skill in skills)
        matched_skill_block = "\n".join(f"- {skill.prompt_view()}" for skill in matched_skills)

        context_section = context_block or "(empty)"
        memory_section = memory_text or "- none"
        available_section = available_skills or "- none"
        matched_section = matched_skill_block or "- none"
        history_section = history_text or "- none"
        scratchpad_section = scratchpad or "- none"
        user_section = user_message

        full_prompt = (
            "[SYSTEM]\n"
            "你是一个可调用工具的 Agent。请根据上下文、记忆、技能和历史消息完成任务。\n"
            "优先考虑匹配技能中的触发条件与参数要求。\n\n"
            f"[CONTEXT]\n{context_section}\n\n"
            f"[MEMORY]\n{memory_section}\n\n"
            f"[MATCHED_SKILLS]\n{matched_section}\n\n"
            f"[AVAILABLE_SKILLS]\n{available_section}\n\n"
            f"[HISTORY]\n{history_section}\n\n"
            f"[SCRATCHPAD]\n{scratchpad_section}\n\n"
            f"[USER]\n{user_section}"
        )

        return PromptBundle(
            context_block=context_section,
            memory_block=memory_section,
            skill_block=available_section,
            history_block=history_section,
            scratchpad_block=scratchpad_section,
            user_block=user_section,
            full_prompt=full_prompt,
        )
