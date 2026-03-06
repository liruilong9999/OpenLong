from __future__ import annotations

from dataclasses import dataclass


TOOL_PROFILES: dict[str, set[str]] = {
    "minimal": {"workspace", "time"},
    "coding": {"file", "http", "shell", "workspace", "time"},
    "research": {"file", "http", "workspace", "time"},
    "full": {"*"},
    "custom": set(),
}


def _normalize_set(items: set[str] | None) -> set[str]:
    return {item.strip().lower() for item in (items or set()) if item and item.strip()}


@dataclass(slots=True)
class ToolPermissionManager:
    profile: str = "custom"
    allowlist: set[str] | None = None
    denylist: set[str] | None = None
    confirmation_required: set[str] | None = None

    def __post_init__(self) -> None:
        self.profile = _normalize_profile(self.profile)
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
            profile="custom",
            allowlist=_csv_to_set(allowlist_csv),
            denylist=_csv_to_set(denylist_csv),
            confirmation_required=_csv_to_set(confirmation_csv),
        )

    @classmethod
    def from_settings(
        cls,
        *,
        profile: str,
        available_tools: list[str],
        allowlist_csv: str = "",
        denylist_csv: str = "",
        confirmation_csv: str = "",
    ) -> "ToolPermissionManager":
        normalized_profile = _normalize_profile(profile)
        allowlist = _resolve_allowlist(
            profile=normalized_profile,
            available_tools=available_tools,
            allowlist_csv=allowlist_csv,
        )
        return cls(
            profile=normalized_profile,
            allowlist=allowlist,
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


def _normalize_profile(profile: str) -> str:
    normalized = (profile or "coding").strip().lower()
    if normalized not in TOOL_PROFILES:
        return "coding"
    return normalized


def _resolve_allowlist(
    *,
    profile: str,
    available_tools: list[str],
    allowlist_csv: str,
) -> set[str]:
    available = {item.strip().lower() for item in available_tools if item and item.strip()}
    base = set(TOOL_PROFILES.get(profile, TOOL_PROFILES["coding"]))
    if "*" in base:
        resolved = set(available)
    else:
        resolved = base & available if available else base

    extra = _csv_to_set(allowlist_csv)
    if extra:
        resolved |= extra & available if available else extra

    return resolved
