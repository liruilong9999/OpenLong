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
    attachment_block: str
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
        attachments: list[dict[str, object]] | None = None,
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
        attachment_section = self._attachment_text(attachments or [])
        scratchpad_section = scratchpad or "- none"
        user_section = user_message

        full_prompt = (
            "[SYSTEM]\n"
            "你是一个可调用工具的 Agent。请根据上下文、记忆、技能和历史消息完成任务。\n"
            "优先参考技能匹配结果及其使用约束。\n\n"
            f"[CONTEXT]\n{context_section}\n\n"
            f"[MEMORY]\n{memory_section}\n\n"
            f"[MATCHED_SKILLS]\n{matched_section}\n\n"
            f"[AVAILABLE_SKILLS]\n{available_section}\n\n"
            f"[HISTORY]\n{history_section}\n\n"
            f"[ATTACHMENTS]\n{attachment_section}\n\n"
            f"[SCRATCHPAD]\n{scratchpad_section}\n\n"
            f"[USER]\n{user_section}"
        )

        return PromptBundle(
            context_block=context_section,
            memory_block=memory_section,
            skill_block=available_section,
            history_block=history_section,
            attachment_block=attachment_section,
            scratchpad_block=scratchpad_section,
            user_block=user_section,
            full_prompt=full_prompt,
        )

    def _attachment_text(self, attachments: list[dict[str, object]]) -> str:
        if not attachments:
            return "- none"

        lines: list[str] = []
        for item in attachments[:8]:
            lines.append(
                f"- filename={item.get('filename') or item.get('saved_name')} "
                f"path={item.get('relative_path')} type={item.get('content_type') or item.get('type')} "
                f"size={item.get('size')}"
            )
        return "\n".join(lines)
