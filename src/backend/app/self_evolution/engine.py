from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class EvolutionFinding:
    kind: str
    severity: str
    title: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "evidence": self.evidence,
        }


@dataclass(slots=True)
class EvolutionSuggestion:
    priority: str
    title: str
    rationale: str
    actions: list[str] = field(default_factory=list)
    suggested_tests: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority": self.priority,
            "title": self.title,
            "rationale": self.rationale,
            "actions": list(self.actions),
            "suggested_tests": list(self.suggested_tests),
        }


@dataclass(slots=True)
class EvolutionReport:
    agent_id: str
    telemetry_summary: dict[str, Any]
    failure_patterns: list[str]
    findings: list[EvolutionFinding] = field(default_factory=list)
    suggestions: list[EvolutionSuggestion] = field(default_factory=list)
    update_plan: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "telemetry_summary": self.telemetry_summary,
            "failure_patterns": list(self.failure_patterns),
            "findings": [item.to_dict() for item in self.findings],
            "suggestions": [item.to_dict() for item in self.suggestions],
            "update_plan": list(self.update_plan),
        }


class SelfEvolutionEngine:
    def evaluate(self, agent_id: str, snapshot: dict[str, Any]) -> EvolutionReport:
        telemetry_summary = self._telemetry_summary(snapshot)
        failure_patterns = self._failure_patterns(snapshot)
        findings = self._findings(snapshot, telemetry_summary, failure_patterns)
        suggestions = self._suggestions(snapshot, findings, failure_patterns)
        update_plan = self._update_plan(suggestions)
        return EvolutionReport(
            agent_id=agent_id,
            telemetry_summary=telemetry_summary,
            failure_patterns=failure_patterns,
            findings=findings,
            suggestions=suggestions,
            update_plan=update_plan,
        )

    def propose_update_plan(self, agent_id: str, snapshot: dict[str, Any] | None = None) -> list[str]:
        report = self.evaluate(agent_id, snapshot or {})
        return report.update_plan

    def _telemetry_summary(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        task_stats = snapshot.get("task_queue") or {}
        tool_stats = snapshot.get("tool_logs") or {}
        model_stats = snapshot.get("model_router") or {}
        automation_stats = snapshot.get("automations") or {}
        readiness = snapshot.get("readiness") or {}

        return {
            "tasks_total": task_stats.get("total", 0),
            "tasks_failed": task_stats.get("failed", 0),
            "tool_total": tool_stats.get("total", 0),
            "tool_failed": tool_stats.get("failed", 0),
            "tool_denied": tool_stats.get("denied", 0),
            "model_calls": model_stats.get("total", 0),
            "model_failed": model_stats.get("failed", 0),
            "model_fallback_activations": model_stats.get("fallback_activations", 0),
            "automation_jobs": automation_stats.get("stats", {}).get("jobs", 0),
            "automation_failed_runs": automation_stats.get("stats", {}).get("failed_runs", 0),
            "readiness_status": readiness.get("status", "unknown"),
            "warning_count": len(snapshot.get("warnings") or []),
            "error_count": len(snapshot.get("errors") or []),
        }

    def _failure_patterns(self, snapshot: dict[str, Any]) -> list[str]:
        patterns: list[str] = []
        events = snapshot.get("recent_events") or []
        tool_logs = snapshot.get("recent_tool_logs") or []
        model_calls = snapshot.get("recent_model_calls") or []
        automation_runs_payload = snapshot.get("automation_runs") or []
        automation_runs = automation_runs_payload.get("items", []) if isinstance(automation_runs_payload, dict) else automation_runs_payload

        denied_tools = [item.get("tool_name") for item in tool_logs if item.get("denied_reason")]
        if denied_tools:
            patterns.append(f"工具拦截集中在: {', '.join(sorted({item for item in denied_tools if item}))}")

        failed_tools = [item.get("tool_name") for item in tool_logs if item.get("success") is False and not item.get("denied_reason")]
        if failed_tools:
            patterns.append(f"工具失败集中在: {', '.join(sorted({item for item in failed_tools if item}))}")

        failed_models = [item for item in model_calls if item.get("success") is False]
        if failed_models:
            patterns.append("模型调用存在失败或配置问题")

        if any(item.get("status") == "failed" for item in automation_runs):
            patterns.append("自动化任务存在失败运行")

        recent_failed_events = [item.get("name") for item in events if str(item.get("name") or "").endswith("failed")]
        if recent_failed_events:
            patterns.append(f"最近失败事件: {', '.join(sorted(set(recent_failed_events)))}")

        return patterns

    def _findings(
        self,
        snapshot: dict[str, Any],
        telemetry_summary: dict[str, Any],
        failure_patterns: list[str],
    ) -> list[EvolutionFinding]:
        findings: list[EvolutionFinding] = []

        if telemetry_summary["readiness_status"] != "ready":
            findings.append(
                EvolutionFinding(
                    kind="readiness",
                    severity="high",
                    title="系统 readiness 未通过",
                    detail="系统存在启动或运行前置条件缺失，影响稳定运行。",
                    evidence={"readiness": snapshot.get("readiness")},
                )
            )

        if telemetry_summary["tool_failed"] > 0 or telemetry_summary["tool_denied"] > 0:
            findings.append(
                EvolutionFinding(
                    kind="tools",
                    severity="medium",
                    title="工具执行存在失败或拦截",
                    detail="工具链存在失败/拒绝，说明执行路径、权限策略或参数设计需要改进。",
                    evidence={
                        "tool_logs": telemetry_summary,
                        "patterns": failure_patterns,
                    },
                )
            )

        if telemetry_summary["model_failed"] > 0 or telemetry_summary["model_fallback_activations"] > 0:
            findings.append(
                EvolutionFinding(
                    kind="models",
                    severity="medium",
                    title="模型链路存在失败或 fallback 激活",
                    detail="模型路由配置、鉴权或提供方稳定性需要进一步治理。",
                    evidence={"model_router": snapshot.get("model_router")},
                )
            )

        if telemetry_summary["tasks_failed"] > 0:
            findings.append(
                EvolutionFinding(
                    kind="tasks",
                    severity="medium",
                    title="任务队列出现失败任务",
                    detail="异步任务存在失败，建议补齐错误场景回归测试与重试策略。",
                    evidence={"task_queue": snapshot.get("task_queue")},
                )
            )

        if telemetry_summary["automation_failed_runs"] > 0:
            findings.append(
                EvolutionFinding(
                    kind="automation",
                    severity="medium",
                    title="自动化任务存在失败运行",
                    detail="cron / webhook / 调度链路存在不稳定因素，需完善可靠性。",
                    evidence={"automations": snapshot.get("automations")},
                )
            )

        if not findings:
            findings.append(
                EvolutionFinding(
                    kind="healthy",
                    severity="low",
                    title="当前系统总体稳定",
                    detail="未发现明显失败模式，可继续强化可观测性和回归测试覆盖。",
                    evidence={"summary": telemetry_summary},
                )
            )

        return findings

    def _suggestions(
        self,
        snapshot: dict[str, Any],
        findings: list[EvolutionFinding],
        failure_patterns: list[str],
    ) -> list[EvolutionSuggestion]:
        suggestions: list[EvolutionSuggestion] = []
        kinds = {item.kind for item in findings}

        if "readiness" in kinds:
            suggestions.append(
                EvolutionSuggestion(
                    priority="P0",
                    title="修复 readiness 阻塞项",
                    rationale="readiness 未通过时，其它优化收益有限。",
                    actions=[
                        "修复配置缺失或目录初始化问题",
                        "将 readiness 校验加入启动前自检",
                    ],
                    suggested_tests=[
                        "增加 gateway 启动失败场景回归测试",
                        "增加 ready/not_ready 状态接口测试",
                    ],
                )
            )

        if "tools" in kinds:
            suggestions.append(
                EvolutionSuggestion(
                    priority="P1",
                    title="优化工具失败与权限策略",
                    rationale="工具是核心执行层，失败或拦截会直接影响任务完成率。",
                    actions=[
                        "分析失败最多的工具并收紧/放宽对应策略",
                        "为常用 shell/file/http 路径增加错误恢复",
                    ],
                    suggested_tests=[
                        "增加失败最多工具的回归测试",
                        "补充审批/权限边界测试",
                    ],
                )
            )

        if "models" in kinds:
            suggestions.append(
                EvolutionSuggestion(
                    priority="P1",
                    title="增强模型路由稳健性",
                    rationale="模型 fallback 已触发，说明主路由质量或配置仍有波动。",
                    actions=[
                        "检查路由规则与 provider 鉴权配置",
                        "为失败模型增加专门 fallback 观测指标",
                    ],
                    suggested_tests=[
                        "增加 provider 失败时的路由回退测试",
                        "增加 dashboard/models 统计校验",
                    ],
                )
            )

        if "tasks" in kinds:
            suggestions.append(
                EvolutionSuggestion(
                    priority="P1",
                    title="补齐异步任务失败路径测试",
                    rationale="任务失败说明队列或任务工厂存在异常分支未充分覆盖。",
                    actions=[
                        "为失败任务补充异常分类与提示",
                        "增加任务重试或幂等保护",
                    ],
                    suggested_tests=[
                        "增加 task.failed 事件回归测试",
                        "增加 submit_and_wait 异常分支测试",
                    ],
                )
            )

        if "automation" in kinds:
            suggestions.append(
                EvolutionSuggestion(
                    priority="P1",
                    title="增强自动化可靠性",
                    rationale="自动化失败会放大周期性任务的不稳定性。",
                    actions=[
                        "为 webhook 增加重试和失败标记",
                        "增加 cron job 的失败复盘信息",
                    ],
                    suggested_tests=[
                        "增加 webhook 投递失败测试",
                        "增加 due-runner 重试逻辑测试",
                    ],
                )
            )

        if not suggestions:
            suggestions.append(
                EvolutionSuggestion(
                    priority="P2",
                    title="继续积累遥测并扩展测试矩阵",
                    rationale="当前系统较稳定，下一步价值在于扩大监控和回归覆盖。",
                    actions=[
                        "扩展事件采样与指标聚合",
                        "增加定期 smoke test",
                    ],
                    suggested_tests=[
                        "增加端到端每日巡检用例",
                    ],
                )
            )

        return suggestions

    def _update_plan(self, suggestions: list[EvolutionSuggestion]) -> list[str]:
        steps: list[str] = []
        for suggestion in suggestions[:5]:
            steps.append(f"[{suggestion.priority}] {suggestion.title}")
            steps.extend(f"- {action}" for action in suggestion.actions[:2])
        return steps
