from __future__ import annotations

import argparse
import atexit
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from typing import Any

import uvicorn


REPO_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = REPO_ROOT / "src" / "backend"
FRONTEND_ROOT = REPO_ROOT / "src" / "frontend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import load_settings  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start the OpenLong runtime from the repository root.")
    parser.add_argument("--host", default="", help="Override the configured backend host.")
    parser.add_argument("--port", type=int, default=0, help="Override the configured backend port.")
    parser.add_argument("--reload", action="store_true", help="Enable backend auto-reload.")
    parser.add_argument("--frontend", action="store_true", help="Start the frontend together with the backend.")
    parser.add_argument("--frontend-only", action="store_true", help="Start only the frontend command.")
    parser.add_argument(
        "--frontend-command",
        choices=["dev", "build", "preview"],
        default="dev",
        help="Frontend npm script to run.",
    )
    parser.add_argument("--frontend-host", default="127.0.0.1", help="Frontend host for dev/preview.")
    parser.add_argument("--frontend-port", type=int, default=5173, help="Frontend port for dev/preview.")
    parser.add_argument(
        "--frontend-install",
        action="store_true",
        help="Run `npm install` before launching the frontend command.",
    )
    return parser


def frontend_npm_executable() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def socket_family_for_host(host: str) -> int:
    return socket.AF_INET6 if ":" in host and host != "0.0.0.0" else socket.AF_INET


def is_port_available(host: str, port: int) -> bool:
    with socket.socket(socket_family_for_host(host), socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def pids_listening_on_port(port: int) -> list[int]:
    if os.name == "nt":
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            check=False,
        )
        pids: set[int] = set()
        target = f":{port}"
        for line in result.stdout.splitlines():
            columns = line.split()
            if len(columns) < 5:
                continue
            local_address = columns[1]
            state = columns[3].upper()
            pid_text = columns[4]
            if not local_address.endswith(target):
                continue
            if state != "LISTENING":
                continue
            try:
                pids.add(int(pid_text))
            except ValueError:
                continue
        return sorted(pids)

    result = subprocess.run(
        ["lsof", "-ti", f"tcp:{port}"],
        capture_output=True,
        text=True,
        check=False,
    )
    pids = []
    for line in result.stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            pids.append(int(text))
        except ValueError:
            continue
    return sorted(set(pids))


def terminate_process_ids(pids: list[int]) -> None:
    if not pids:
        return

    if os.name == "nt":
        for pid in pids:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
        return

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            continue


def ensure_port_available(host: str, port: int, label: str, wait_seconds: float = 5.0) -> list[int]:
    if is_port_available(host, port):
        return []

    pids = pids_listening_on_port(port)
    if not pids:
        raise RuntimeError(f"{label} port {port} is busy, but no listening PID was found")

    print(f"[OpenLong] {label} port {port} is busy, stopping PIDs: {', '.join(str(pid) for pid in pids)}")
    terminate_process_ids(pids)

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if is_port_available(host, port):
            return pids
        time.sleep(0.2)

    raise RuntimeError(f"Failed to free {label} port {port} after stopping PIDs: {', '.join(str(pid) for pid in pids)}")


def build_frontend_command(script: str, host: str, port: int) -> list[str]:
    command = [frontend_npm_executable(), "run", script]
    if script in {"dev", "preview"}:
        command.extend(["--", "--host", host, "--port", str(port)])
    return command


def build_frontend_env(api_base_url: str) -> dict[str, str]:
    env = os.environ.copy()
    env["VITE_API_BASE_URL"] = api_base_url
    return env


def run_frontend_install() -> None:
    subprocess.run(
        [frontend_npm_executable(), "install"],
        cwd=FRONTEND_ROOT,
        check=True,
    )


def start_frontend_process(
    *,
    script: str,
    host: str,
    port: int,
    api_base_url: str,
) -> subprocess.Popen[str]:
    return subprocess.Popen(
        build_frontend_command(script=script, host=host, port=port),
        cwd=FRONTEND_ROOT,
        env=build_frontend_env(api_base_url),
        text=True,
    )


def stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def backend_api_base(host: str, port: int) -> str:
    resolved_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{resolved_host}:{port}"


def print_runtime_summary(*, host: str, port: int, frontend_enabled: bool, frontend_script: str, frontend_host: str, frontend_port: int, api_base_url: str, model_provider: str, model_name: str, key_file_path: str) -> None:
    print(f"[OpenLong] backend root: {BACKEND_ROOT}")
    print(f"[OpenLong] frontend root: {FRONTEND_ROOT}")
    print(f"[OpenLong] model: {model_provider or 'OpenAI'} / {model_name}")
    print(f"[OpenLong] key file: {key_file_path}")
    print(f"[OpenLong] backend: http://{host}:{port}")
    print(f"[OpenLong] frontend api base: {api_base_url}")
    if frontend_enabled:
        print(f"[OpenLong] frontend command: npm run {frontend_script}")
        print(f"[OpenLong] frontend: http://{frontend_host}:{frontend_port}")


def main() -> None:
    args = build_parser().parse_args()
    settings = load_settings()
    host = args.host or settings.api_host
    port = args.port or settings.api_port
    frontend_port = args.frontend_port

    ensure_port_available(host, port, "backend")
    if (args.frontend or args.frontend_only) and args.frontend_command in {"dev", "preview"}:
        ensure_port_available(args.frontend_host, frontend_port, "frontend")

    api_base_url = backend_api_base(host, port)
    frontend_process: subprocess.Popen[str] | None = None

    print_runtime_summary(
        host=host,
        port=port,
        frontend_enabled=args.frontend or args.frontend_only,
        frontend_script=args.frontend_command,
        frontend_host=args.frontend_host,
        frontend_port=frontend_port,
        api_base_url=api_base_url,
        model_provider=settings.model_provider,
        model_name=settings.openai_model,
        key_file_path=settings.key_file_path,
    )

    if args.frontend_install:
        run_frontend_install()

    if args.frontend or args.frontend_only:
        frontend_process = start_frontend_process(
            script=args.frontend_command,
            host=args.frontend_host,
            port=frontend_port,
            api_base_url=api_base_url,
        )
        atexit.register(stop_process, frontend_process)

    if args.frontend_only:
        if frontend_process is None:
            return
        try:
            raise SystemExit(frontend_process.wait())
        finally:
            stop_process(frontend_process)

    def _handle_signal(signum: int, frame: Any) -> None:
        del frame
        stop_process(frontend_process)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        uvicorn.run(
            "app.main:app",
            host=host,
            port=port,
            reload=args.reload,
            app_dir=str(BACKEND_ROOT),
            reload_dirs=[str(BACKEND_ROOT)] if args.reload else None,
        )
    finally:
        stop_process(frontend_process)


if __name__ == "__main__":
    main()
