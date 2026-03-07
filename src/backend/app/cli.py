from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any, Callable

import uvicorn

from app.acp_bridge import ACPBridge
from app.core.config import load_settings
from app.gateway.runtime import GatewayRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenLong local CLI")
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Run the backend server")
    serve_parser.add_argument("--host", default="", help="Override backend host")
    serve_parser.add_argument("--port", type=int, default=0, help="Override backend port")
    serve_parser.set_defaults(handler=_handle_serve)

    health_parser = subparsers.add_parser("health", help="Show runtime health")
    health_parser.add_argument("--agent-id", default="main")
    health_parser.add_argument("--task-type", default="chat")
    _add_json_flag(health_parser)
    health_parser.set_defaults(handler=_handle_health)

    chat_parser = subparsers.add_parser("chat", help="Send one message through the local runtime")
    chat_parser.add_argument("--message", required=True)
    chat_parser.add_argument("--session-id", default="")
    chat_parser.add_argument("--agent-id", default="main")
    chat_parser.add_argument("--source", default="cli")
    _add_json_flag(chat_parser)
    chat_parser.set_defaults(handler=_handle_chat)

    sessions_parser = subparsers.add_parser("sessions", help="Inspect or manage sessions")
    sessions_subparsers = sessions_parser.add_subparsers(dest="sessions_command", required=True)

    sessions_list_parser = sessions_subparsers.add_parser("list", help="List sessions")
    _add_json_flag(sessions_list_parser)
    sessions_list_parser.set_defaults(handler=_handle_sessions_list)

    sessions_create_parser = sessions_subparsers.add_parser("create", help="Create a session")
    sessions_create_parser.add_argument("--session-id", default="")
    sessions_create_parser.add_argument("--agent-id", default="main")
    _add_json_flag(sessions_create_parser)
    sessions_create_parser.set_defaults(handler=_handle_sessions_create)

    sessions_history_parser = sessions_subparsers.add_parser("history", help="Show session history")
    sessions_history_parser.add_argument("--session-id", required=True)
    sessions_history_parser.add_argument("--limit", type=int, default=20)
    _add_json_flag(sessions_history_parser)
    sessions_history_parser.set_defaults(handler=_handle_sessions_history)

    sessions_assign_parser = sessions_subparsers.add_parser("assign", help="Assign a session to an agent")
    sessions_assign_parser.add_argument("--session-id", required=True)
    sessions_assign_parser.add_argument("--agent-id", required=True)
    _add_json_flag(sessions_assign_parser)
    sessions_assign_parser.set_defaults(handler=_handle_sessions_assign)

    sessions_close_parser = sessions_subparsers.add_parser("close", help="Close a session")
    sessions_close_parser.add_argument("--session-id", required=True)
    sessions_close_parser.add_argument("--reason", default="manual")
    _add_json_flag(sessions_close_parser)
    sessions_close_parser.set_defaults(handler=_handle_sessions_close)

    tools_parser = subparsers.add_parser("tools", help="Inspect or execute tools")
    tools_subparsers = tools_parser.add_subparsers(dest="tools_command", required=True)

    tools_list_parser = tools_subparsers.add_parser("list", help="List tools")
    _add_json_flag(tools_list_parser)
    tools_list_parser.set_defaults(handler=_handle_tools_list)

    tools_logs_parser = tools_subparsers.add_parser("logs", help="Show tool logs")
    tools_logs_parser.add_argument("--limit", type=int, default=20)
    tools_logs_parser.add_argument("--tool-name", default="")
    _add_json_flag(tools_logs_parser)
    tools_logs_parser.set_defaults(handler=_handle_tools_logs)

    tools_run_parser = tools_subparsers.add_parser("run", help="Execute a tool")
    tools_run_parser.add_argument("--tool-name", required=True)
    tools_run_parser.add_argument("--session-id", default="cli-tool-session")
    tools_run_parser.add_argument("--agent-id", default="main")
    tools_run_parser.add_argument("--args", default="{}", help="JSON tool args")
    tools_run_parser.add_argument("--confirm", action="store_true")
    _add_json_flag(tools_run_parser)
    tools_run_parser.set_defaults(handler=_handle_tools_run)

    approvals_parser = tools_subparsers.add_parser("approvals", help="List pending tool approvals")
    approvals_parser.add_argument("--limit", type=int, default=20)
    _add_json_flag(approvals_parser)
    approvals_parser.set_defaults(handler=_handle_tools_approvals)

    approve_parser = tools_subparsers.add_parser("approve", help="Approve a pending tool approval")
    approve_parser.add_argument("--approval-id", required=True)
    _add_json_flag(approve_parser)
    approve_parser.set_defaults(handler=_handle_tools_approve)

    reject_parser = tools_subparsers.add_parser("reject", help="Reject a pending tool approval")
    reject_parser.add_argument("--approval-id", required=True)
    reject_parser.add_argument("--reason", default="manual reject")
    _add_json_flag(reject_parser)
    reject_parser.set_defaults(handler=_handle_tools_reject)

    workspace_parser = subparsers.add_parser("workspace", help="Inspect workspaces")
    workspace_subparsers = workspace_parser.add_subparsers(dest="workspace_command", required=True)

    workspace_list_parser = workspace_subparsers.add_parser("list", help="List workspaces")
    _add_json_flag(workspace_list_parser)
    workspace_list_parser.set_defaults(handler=_handle_workspace_list)

    workspace_show_parser = workspace_subparsers.add_parser("show", help="Show one workspace")
    workspace_show_parser.add_argument("--agent-id", default="main")
    _add_json_flag(workspace_show_parser)
    workspace_show_parser.set_defaults(handler=_handle_workspace_show)

    workspace_templates_parser = workspace_subparsers.add_parser("templates", help="List workspace templates")
    _add_json_flag(workspace_templates_parser)
    workspace_templates_parser.set_defaults(handler=_handle_workspace_templates)

    workspace_logs_parser = workspace_subparsers.add_parser("logs", help="Show workspace logs")
    workspace_logs_parser.add_argument("--agent-id", default="main")
    workspace_logs_parser.add_argument("--limit", type=int, default=20)
    _add_json_flag(workspace_logs_parser)
    workspace_logs_parser.set_defaults(handler=_handle_workspace_logs)

    doctor_parser = subparsers.add_parser("doctor", help="Run local runtime diagnostics")
    _add_json_flag(doctor_parser)
    doctor_parser.set_defaults(handler=_handle_doctor)

    acp_parser = subparsers.add_parser("acp", help="Run ACP stdio bridge")
    acp_parser.add_argument("--agent-id", default="main")
    acp_parser.add_argument("--session-prefix", default="acp")
    acp_parser.set_defaults(handler=_handle_acp)

    return parser


def main(argv: list[str] | None = None) -> int:
    args_list = list(argv or sys.argv[1:])
    if not args_list:
        args_list = ["serve"]

    parser = build_parser()
    args = parser.parse_args(args_list)
    handler: Callable[[argparse.Namespace], int] | None = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)


def _runtime() -> GatewayRuntime:
    load_settings.cache_clear()
    return GatewayRuntime.from_settings(load_settings())


def _emit(payload: Any, *, as_json: bool, fallback_text: str | None = None) -> int:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if fallback_text is not None:
        print(fallback_text)
        return 0
    if isinstance(payload, str):
        print(payload)
        return 0
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _parse_json_args(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON args: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("tool args must be a JSON object")
    return payload


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Print JSON output")


def _handle_serve(args: argparse.Namespace) -> int:
    settings = load_settings()
    host = args.host or settings.api_host
    port = args.port or settings.api_port
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
    return 0


def _handle_health(args: argparse.Namespace) -> int:
    runtime = _runtime()
    endpoint = runtime.model_router.endpoint_for(args.agent_id, task_type=args.task_type)
    payload = {
        "status": "ok",
        "agent_id": args.agent_id,
        "task_type": args.task_type,
        "provider": endpoint.provider,
        "model": endpoint.model,
        "key_configured": endpoint.has_api_key,
    }
    return _emit(payload, as_json=args.json, fallback_text=f"{payload['status']} {payload['provider']} {payload['model']}")


def _handle_chat(args: argparse.Namespace) -> int:
    runtime = _runtime()
    session_id = args.session_id or runtime.create_session(preferred_agent_id=args.agent_id)["session_id"]
    payload = asyncio.run(
        runtime.handle_user_message(
            session_id=session_id,
            user_message=args.message,
            preferred_agent_id=args.agent_id,
            source=args.source,
        )
    )
    return _emit(payload, as_json=args.json, fallback_text=payload["reply"])


def _handle_sessions_list(args: argparse.Namespace) -> int:
    runtime = _runtime()
    payload = runtime.session_manager.list_sessions(include_closed=True)
    text = "\n".join(f"{item['session_id']} [{item['agent_id']}] {item['status']} messages={item['message_count']}" for item in payload) or "(no sessions)"
    return _emit(payload, as_json=args.json, fallback_text=text)


def _handle_sessions_create(args: argparse.Namespace) -> int:
    runtime = _runtime()
    payload = runtime.create_session(session_id=args.session_id or None, preferred_agent_id=args.agent_id)
    return _emit(payload, as_json=args.json, fallback_text=f"created {payload['session_id']} [{payload['agent_id']}]")


def _handle_sessions_history(args: argparse.Namespace) -> int:
    runtime = _runtime()
    payload = runtime.session_manager.get_history(args.session_id, limit=args.limit)
    text = "\n".join(f"[{item['role']}] {item['content']}" for item in payload) or "(empty history)"
    return _emit(payload, as_json=args.json, fallback_text=text)


def _handle_sessions_assign(args: argparse.Namespace) -> int:
    runtime = _runtime()
    payload = runtime.assign_agent_to_session(session_id=args.session_id, agent_id=args.agent_id)
    if payload is None:
        raise SystemExit("session not found")
    return _emit(payload, as_json=args.json, fallback_text=f"assigned {args.session_id} -> {args.agent_id}")


def _handle_sessions_close(args: argparse.Namespace) -> int:
    runtime = _runtime()
    closed = runtime.close_session(session_id=args.session_id, reason=args.reason)
    payload = {"closed": closed, "session_id": args.session_id, "reason": args.reason}
    return _emit(payload, as_json=args.json, fallback_text=f"closed={closed} {args.session_id}")


def _handle_tools_list(args: argparse.Namespace) -> int:
    runtime = _runtime()
    payload = runtime.list_tools()
    text = "\n".join(f"{item['name']}: {item['description']}" for item in payload["tools"])
    return _emit(payload, as_json=args.json, fallback_text=text)


def _handle_tools_logs(args: argparse.Namespace) -> int:
    runtime = _runtime()
    payload = runtime.tool_logs(limit=args.limit, tool_name=args.tool_name or None)
    text = "\n".join(
        f"{item['tool_name']} success={item['success']} {item['result_preview']}"
        for item in payload["items"]
    ) or "(no logs)"
    return _emit(payload, as_json=args.json, fallback_text=text)


def _handle_tools_run(args: argparse.Namespace) -> int:
    runtime = _runtime()
    payload = asyncio.run(
        runtime.execute_tool_task(
            tool_name=args.tool_name,
            session_id=args.session_id,
            agent_id=args.agent_id,
            args=_parse_json_args(args.args),
            caller="cli",
            confirm=args.confirm,
        )
    )
    return _emit(payload, as_json=args.json, fallback_text=payload["content"])


def _handle_tools_approvals(args: argparse.Namespace) -> int:
    runtime = _runtime()
    payload = runtime.tool_approvals(limit=args.limit)
    text = "\n".join(f"{item['approval_id']} {item['tool_name']} {item['category']} {item['command_preview']}" for item in payload["items"]) or "(no pending approvals)"
    return _emit(payload, as_json=args.json, fallback_text=text)


def _handle_tools_approve(args: argparse.Namespace) -> int:
    runtime = _runtime()
    payload = asyncio.run(runtime.approve_tool_approval(args.approval_id))
    if payload is None:
        raise SystemExit("approval not found")
    return _emit(payload, as_json=args.json, fallback_text=f"approved {args.approval_id} -> {payload['status']}")


def _handle_tools_reject(args: argparse.Namespace) -> int:
    runtime = _runtime()
    payload = runtime.reject_tool_approval(args.approval_id, reason=args.reason)
    if payload is None:
        raise SystemExit("approval not found")
    return _emit(payload, as_json=args.json, fallback_text=f"rejected {args.approval_id}")


def _handle_workspace_list(args: argparse.Namespace) -> int:
    runtime = _runtime()
    payload = runtime.list_workspaces()
    text = "\n".join(f"{item['agent_id']} path={item['path']}" for item in payload) or "(no workspaces)"
    return _emit(payload, as_json=args.json, fallback_text=text)


def _handle_workspace_show(args: argparse.Namespace) -> int:
    runtime = _runtime()
    payload = runtime.get_workspace(args.agent_id)
    if payload is None:
        raise SystemExit("workspace not found")
    return _emit(payload, as_json=args.json, fallback_text=f"{payload['agent_id']} -> {payload['path']}")


def _handle_workspace_templates(args: argparse.Namespace) -> int:
    runtime = _runtime()
    payload = runtime.workspace_templates()
    text = "\n".join(f"{item['name']}: {item['description']}" for item in payload["templates"])
    return _emit(payload, as_json=args.json, fallback_text=text)


def _handle_workspace_logs(args: argparse.Namespace) -> int:
    runtime = _runtime()
    payload = runtime.workspace_logs(agent_id=args.agent_id, limit=args.limit)
    text = "\n".join(f"{item['event_name']} {item['message']}" for item in payload["items"]) or "(no workspace logs)"
    return _emit(payload, as_json=args.json, fallback_text=text)


def _handle_doctor(args: argparse.Namespace) -> int:
    runtime = _runtime()
    payload = runtime.doctor()
    readiness = payload.get("readiness") or {}
    checks = readiness.get("checks") or {}
    warnings = payload.get("warnings") or []
    errors = payload.get("errors") or []
    self_evolution = payload.get("self_evolution") or {}
    text_lines = [f"status: {payload['status']}"]
    text_lines.extend(f"{name}: {'OK' if value else 'WARN'}" for name, value in checks.items())
    if warnings:
        text_lines.append("warnings:")
        text_lines.extend(f"- {item}" for item in warnings)
    if errors:
        text_lines.append("errors:")
        text_lines.extend(f"- {item}" for item in errors)
    suggestions = self_evolution.get("suggestions") or []
    if suggestions:
        text_lines.append("self-evolution suggestions:")
        for item in suggestions[:3]:
            text_lines.append(f"- [{item.get('priority')}] {item.get('title')}")
    text = "\n".join(text_lines)
    return _emit(payload, as_json=args.json, fallback_text=text)


def _handle_acp(args: argparse.Namespace) -> int:
    runtime = _runtime()
    bridge = ACPBridge(runtime, default_agent_id=args.agent_id, session_prefix=args.session_prefix)
    return asyncio.run(bridge.run_stdio(sys.stdin, sys.stdout))
