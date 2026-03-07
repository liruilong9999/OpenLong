from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any


AUTH_MODES = {"disabled", "token", "password", "either"}
AUTH_EXEMPT_PATHS = {"/health", "/ready", "/docs", "/redoc", "/openapi.json"}


def is_loopback_host(host: str) -> bool:
    normalized = (host or "").strip().lower()
    return normalized in {"", "127.0.0.1", "localhost", "::1"}


def validate_gateway_settings(settings: Any) -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    mode = gateway_auth_mode(settings)
    if mode not in AUTH_MODES:
        errors.append(f"unsupported gateway_auth_mode: {mode}")
        return {"errors": errors, "warnings": warnings}

    token = str(getattr(settings, "gateway_auth_token", "") or "").strip()
    password = str(getattr(settings, "gateway_auth_password", "") or "").strip()

    if mode == "token" and not token:
        errors.append("gateway_auth_mode=token requires gateway_auth_token")
    elif mode == "password" and not password:
        errors.append("gateway_auth_mode=password requires gateway_auth_password")
    elif mode == "either" and not (token or password):
        errors.append("gateway_auth_mode=either requires gateway_auth_token or gateway_auth_password")

    if not is_loopback_host(str(getattr(settings, "api_host", ""))) and mode == "disabled":
        warnings.append("Gateway is bound to a non-loopback host without auth; this is unsafe on LAN/controlled networks.")

    workspace_root = str(getattr(settings, "workspace_root", "") or "").strip()
    if not workspace_root:
        errors.append("workspace_root cannot be empty")

    return {"errors": errors, "warnings": warnings}


def gateway_auth_mode(settings: Any) -> str:
    return str(getattr(settings, "gateway_auth_mode", "disabled") or "disabled").strip().lower()


def gateway_auth_enabled(settings: Any) -> bool:
    return gateway_auth_mode(settings) != "disabled"


def authenticate_credentials(
    *,
    settings: Any,
    headers: Mapping[str, str],
    query_params: Mapping[str, str] | None = None,
) -> tuple[bool, str | None]:
    mode = gateway_auth_mode(settings)
    if mode == "disabled":
        return True, None

    token = _extract_bearer_token(headers) or _extract_header(headers, "x-openlong-token")
    password = _extract_password(headers) or _extract_header(headers, "x-openlong-password")

    query_map = query_params or {}
    token = token or str(query_map.get("token") or "").strip() or None
    password = password or str(query_map.get("password") or "").strip() or None

    configured_token = str(getattr(settings, "gateway_auth_token", "") or "").strip()
    configured_password = str(getattr(settings, "gateway_auth_password", "") or "").strip()

    token_ok = bool(configured_token and token == configured_token)
    password_ok = bool(configured_password and password == configured_password)

    if mode == "token":
        return (token_ok, None if token_ok else "token authentication failed")
    if mode == "password":
        return (password_ok, None if password_ok else "password authentication failed")
    return ((token_ok or password_ok), None if (token_ok or password_ok) else "gateway authentication failed")


def _extract_header(headers: Mapping[str, str], key: str) -> str | None:
    for header_key, value in headers.items():
        if header_key.lower() == key.lower() and str(value).strip():
            return str(value).strip()
    return None


def _extract_bearer_token(headers: Mapping[str, str]) -> str | None:
    authorization = _extract_header(headers, "authorization")
    if not authorization:
        return None
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def _extract_password(headers: Mapping[str, str]) -> str | None:
    authorization = _extract_header(headers, "authorization")
    if authorization and authorization.lower().startswith("basic "):
        encoded = authorization[6:].strip()
        try:
            decoded = base64.b64decode(encoded).decode("utf-8")
        except Exception:  # noqa: BLE001
            return None
        if ":" in decoded:
            return decoded.split(":", 1)[1]
        return decoded
    return None
