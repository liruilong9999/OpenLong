from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Any
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ToolApprovalStatus(str, Enum):
    PENDING = "pending"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


@dataclass(slots=True)
class ToolApproval:
    approval_id: str
    tool_name: str
    session_id: str
    agent_id: str
    caller: str
    args: dict[str, Any]
    command_preview: str
    category: str
    created_at: datetime = field(default_factory=_utc_now)
    status: ToolApprovalStatus = ToolApprovalStatus.PENDING
    decided_at: datetime | None = None
    decision_reason: str | None = None
    result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "tool_name": self.tool_name,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "caller": self.caller,
            "args": dict(self.args),
            "command_preview": self.command_preview,
            "category": self.category,
            "created_at": self.created_at.isoformat(),
            "status": self.status.value,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "decision_reason": self.decision_reason,
            "result": self.result,
        }


class ToolApprovalStore:
    def __init__(self) -> None:
        self._items: dict[str, ToolApproval] = {}
        self._lock = Lock()

    def create(
        self,
        *,
        tool_name: str,
        session_id: str,
        agent_id: str,
        caller: str,
        args: dict[str, Any],
        command_preview: str,
        category: str,
    ) -> ToolApproval:
        approval = ToolApproval(
            approval_id=str(uuid4()),
            tool_name=tool_name,
            session_id=session_id,
            agent_id=agent_id,
            caller=caller,
            args=dict(args),
            command_preview=command_preview,
            category=category,
        )
        with self._lock:
            self._items[approval.approval_id] = approval
        return approval

    def get(self, approval_id: str) -> ToolApproval | None:
        with self._lock:
            return self._items.get(approval_id)

    def list(self, *, status: ToolApprovalStatus | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._items.values())

        if status is not None:
            items = [item for item in items if item.status == status]

        items.sort(key=lambda item: item.created_at, reverse=True)
        return [item.to_dict() for item in items[: max(limit, 0)]]

    def stats(self) -> dict[str, int]:
        with self._lock:
            items = list(self._items.values())
        return {
            "total": len(items),
            "pending": sum(1 for item in items if item.status == ToolApprovalStatus.PENDING),
            "rejected": sum(1 for item in items if item.status == ToolApprovalStatus.REJECTED),
            "executed": sum(1 for item in items if item.status == ToolApprovalStatus.EXECUTED),
            "failed": sum(1 for item in items if item.status == ToolApprovalStatus.FAILED),
        }

    def reject(self, approval_id: str, reason: str = "manual reject") -> ToolApproval | None:
        with self._lock:
            approval = self._items.get(approval_id)
            if approval is None or approval.status != ToolApprovalStatus.PENDING:
                return None
            approval.status = ToolApprovalStatus.REJECTED
            approval.decision_reason = reason
            approval.decided_at = _utc_now()
            return approval

    def resolve(self, approval_id: str, *, success: bool, result: dict[str, Any], reason: str | None = None) -> ToolApproval | None:
        with self._lock:
            approval = self._items.get(approval_id)
            if approval is None or approval.status != ToolApprovalStatus.PENDING:
                return None
            approval.status = ToolApprovalStatus.EXECUTED if success else ToolApprovalStatus.FAILED
            approval.result = result
            approval.decision_reason = reason
            approval.decided_at = _utc_now()
            return approval
