from __future__ import annotations

from app.agent.types import ModelOutput, ToolCallTrace


class ResponseGenerator:
    def generate(
        self,
        user_message: str,
        model_outputs: list[ModelOutput],
        tool_traces: list[ToolCallTrace],
    ) -> str:
        lines: list[str] = []

        if tool_traces:
            pending_count = sum(1 for trace in tool_traces if trace.data.get("pending_approval"))
            success_count = sum(1 for trace in tool_traces if trace.success)
            fail_count = len(tool_traces) - success_count - pending_count
            lines.append(f"工具执行完成：成功 {success_count}，待审批 {pending_count}，失败 {max(fail_count, 0)}。")

            for trace in tool_traces[-3:]:
                status = "PENDING" if trace.data.get("pending_approval") else "OK" if trace.success else "FAILED"
                preview = trace.content.replace("\n", " ")[:220]
                lines.append(f"- [{status}] {trace.call.name}: {preview}")

        if model_outputs:
            lines.append(model_outputs[-1].text)

        if not lines:
            return f"已收到请求：{user_message}"

        return "\n".join(lines)
