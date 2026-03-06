from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
START_FILE = REPO_ROOT / "start.py"


def _load_start_module():
    spec = spec_from_file_location("openlong_start", START_FILE)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_start_script_frontend_helpers() -> None:
    start_module = _load_start_module()

    command = start_module.build_frontend_command("dev", "127.0.0.1", 5173)
    assert command[1:3] == ["run", "dev"]
    assert "--host" in command
    assert "--port" in command

    preview_command = start_module.build_frontend_command("preview", "0.0.0.0", 4173)
    assert preview_command[1:3] == ["run", "preview"]
    assert preview_command[-1] == "4173"

    build_command = start_module.build_frontend_command("build", "127.0.0.1", 5173)
    assert build_command == [start_module.frontend_npm_executable(), "run", "build"]

    assert start_module.backend_api_base("0.0.0.0", 8000) == "http://127.0.0.1:8000"
    assert start_module.backend_api_base("127.0.0.1", 8000) == "http://127.0.0.1:8000"

    env = start_module.build_frontend_env("http://127.0.0.1:8000")
    assert env["VITE_API_BASE_URL"] == "http://127.0.0.1:8000"


def test_start_script_parser_supports_frontend_flags() -> None:
    start_module = _load_start_module()
    parser = start_module.build_parser()

    args = parser.parse_args(
        [
            "--reload",
            "--frontend",
            "--frontend-command",
            "preview",
            "--frontend-host",
            "0.0.0.0",
            "--frontend-port",
            "4173",
            "--frontend-install",
        ]
    )

    assert args.reload is True
    assert args.frontend is True
    assert args.frontend_only is False
    assert args.frontend_command == "preview"
    assert args.frontend_host == "0.0.0.0"
    assert args.frontend_port == 4173
    assert args.frontend_install is True


def test_ensure_port_available_passthrough_when_free() -> None:
    start_module = _load_start_module()

    with patch.object(start_module, "is_port_available", return_value=True):
        stopped = start_module.ensure_port_available("127.0.0.1", 8000, "backend")

    assert stopped == []


def test_ensure_port_available_stops_bound_processes() -> None:
    start_module = _load_start_module()

    with (
        patch.object(start_module, "is_port_available", side_effect=[False, False, True]),
        patch.object(start_module, "pids_listening_on_port", return_value=[7504, 24376]),
        patch.object(start_module, "terminate_process_ids") as terminate_mock,
        patch.object(start_module.time, "sleep", return_value=None),
    ):
        stopped = start_module.ensure_port_available("127.0.0.1", 8000, "backend")

    terminate_mock.assert_called_once_with([7504, 24376])
    assert stopped == [7504, 24376]


def test_windows_port_pid_parsing_prefers_listeners() -> None:
    start_module = _load_start_module()
    netstat_output = "\n".join(
        [
            "  TCP    0.0.0.0:8000           0.0.0.0:0              LISTENING       7504",
            "  TCP    127.0.0.1:8000         127.0.0.1:50000        ESTABLISHED     8080",
            "  TCP    0.0.0.0:8000           0.0.0.0:0              LISTENING       24376",
        ]
    )

    with (
        patch.object(start_module.os, "name", "nt"),
        patch.object(start_module.subprocess, "run", return_value=SimpleNamespace(stdout=netstat_output)),
    ):
        pids = start_module.pids_listening_on_port(8000)

    assert pids == [7504, 24376]
