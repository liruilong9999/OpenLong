from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


_BLOCKED_SHELL_PATTERNS = [
    "rm -rf",
    "del /f /q",
    "format ",
    "mkfs",
    "shutdown",
    "reboot",
    "reg delete",
    "net user",
    "curl ",
    "| sh",
    "| bash",
    "powershell -enc",
]

_ALLOWED_SHELL_PREFIXES = [
    "echo",
    "dir",
    "ls",
    "pwd",
    "type",
    "cat",
    "get-childitem",
    "get-location",
    "where",
    "python --version",
    "pip --version",
    "git status",
]


class ToolSandbox:
    def validate(self, tool_name: str, args: dict[str, Any]) -> tuple[bool, str | None, dict[str, Any]]:
        normalized = tool_name.lower().strip()
        payload = dict(args)

        if normalized == "shell":
            return self._validate_shell(payload)
        if normalized == "http":
            return self._validate_http(payload)
        if normalized == "file":
            return self._validate_file(payload)

        return True, None, payload

    def _validate_shell(self, payload: dict[str, Any]) -> tuple[bool, str | None, dict[str, Any]]:
        command = str(payload.get("input", "")).strip()
        if not command:
            return False, "missing command", payload

        if len(command) > 500:
            return False, "command too long", payload

        lowered = command.lower()
        for pattern in _BLOCKED_SHELL_PATTERNS:
            if pattern in lowered:
                return False, f"dangerous shell pattern blocked: {pattern}", payload

        if not any(lowered.startswith(prefix) for prefix in _ALLOWED_SHELL_PREFIXES):
            return False, "shell command not allowed by sandbox prefix policy", payload

        timeout = float(payload.get("timeout", 15.0))
        payload["timeout"] = max(1.0, min(timeout, 30.0))
        return True, None, payload

    def _validate_http(self, payload: dict[str, Any]) -> tuple[bool, str | None, dict[str, Any]]:
        url = str(payload.get("url", "")).strip()
        if not url:
            return False, "missing url", payload

        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"}:
            return False, "only http/https urls are allowed", payload

        host = (parsed.hostname or "").lower()
        if not host:
            return False, "invalid url host", payload

        if host in {"localhost", "127.0.0.1", "::1"}:
            return False, "localhost is blocked in sandbox", payload

        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False, "private or local network targets are blocked", payload
        except ValueError:
            # Non-IP hostname: allow by default.
            pass

        timeout = float(payload.get("timeout", 20.0))
        payload["timeout"] = max(1.0, min(timeout, 45.0))
        return True, None, payload

    def _validate_file(self, payload: dict[str, Any]) -> tuple[bool, str | None, dict[str, Any]]:
        path = str(payload.get("path", "")).strip()
        if not path:
            return False, "missing path", payload

        raw = Path(path)
        if raw.is_absolute():
            return False, "absolute file path is blocked", payload

        parts = set(raw.parts)
        if ".." in parts:
            return False, "relative path traversal is blocked", payload

        action = str(payload.get("action", "read")).lower()
        if action not in {"read", "write"}:
            return False, "unsupported file action", payload

        if action == "write":
            content = str(payload.get("content", ""))
            if len(content) > 1_000_000:
                return False, "write content too large", payload

        return True, None, payload
