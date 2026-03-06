from __future__ import annotations

from dataclasses import dataclass


def _normalize_set(items: set[str] | None) -> set[str]:
    return {item.strip().lower() for item in (items or set()) if item and item.strip()}


@dataclass(slots=True)
class ToolPermissionManager:
    allowlist: set[str] | None = None
    denylist: set[str] | None = None
    confirmation_required: set[str] | None = None

    def __post_init__(self) -> None:
        self.allowlist = _normalize_set(self.allowlist)
        self.denylist = _normalize_set(self.denylist)
        self.confirmation_required = _normalize_set(self.confirmation_required)

    @classmethod
    def from_csv(
        cls,
        *,
        allowlist_csv: str = "",
        denylist_csv: str = "",
        confirmation_csv: str = "",
    ) -> "ToolPermissionManager":
        return cls(
            allowlist=_csv_to_set(allowlist_csv),
            denylist=_csv_to_set(denylist_csv),
            confirmation_required=_csv_to_set(confirmation_csv),
        )

    def is_allowed(self, tool_name: str) -> tuple[bool, str | None]:
        name = tool_name.lower().strip()
        if not name:
            return False, "empty tool name"

        if name in (self.denylist or set()):
            return False, f"tool denied by denylist: {name}"

        if self.allowlist and name not in self.allowlist:
            return False, f"tool not in allowlist: {name}"

        return True, None

    def requires_confirmation(self, tool_name: str) -> bool:
        return tool_name.lower().strip() in (self.confirmation_required or set())

    def authorize(
        self,
        *,
        tool_name: str,
        caller: str,
        confirm: bool,
    ) -> tuple[bool, str | None]:
        allowed, reason = self.is_allowed(tool_name)
        if not allowed:
            return False, reason

        if self.requires_confirmation(tool_name) and caller != "system" and not confirm:
            return False, f"tool requires confirmation: {tool_name}"

        return True, None


def _csv_to_set(text: str) -> set[str]:
    return {item.strip().lower() for item in (text or "").split(",") if item.strip()}
