from __future__ import annotations

import subprocess
import time
import os
from dataclasses import dataclass

from commander.models import Action, normalize_input_names
from commander.storage import Storage


@dataclass(slots=True)
class RunResult:
    run_id: int
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int | None


def build_command(action: Action, inputs: dict[str, str] | None = None) -> list[str]:
    inputs = normalize_run_inputs(action, inputs)
    if action.type == "cmd":
        return ["cmd.exe", "/c", action.command or ""]
    if action.type == "powershell":
        return [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-NonInteractive",
            "-Command",
            action.command or "",
        ]
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-NonInteractive",
        "-File",
        action.script_path or "",
    ]
    for name, value in inputs.items():
        command.extend([f"-{name}", value])
    return command


def run_action(action: Action, storage: Storage, inputs: dict[str, str] | None = None) -> RunResult:
    run_id = storage.create_run(action.id, action.name, "running")
    command = build_command(action, inputs)
    env = build_env(action, inputs)

    if action.mode == "start":
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, **hidden_subprocess_kwargs())
        return RunResult(run_id=run_id, status="running", exit_code=None, stdout="", stderr="", duration_ms=None)

    start = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=action.timeout_seconds,
            check=False,
            env=env,
            **hidden_subprocess_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        stdout = _decode_timeout_output(exc.stdout)
        stderr = _decode_timeout_output(exc.stderr)
        storage.finish_run(
            run_id,
            status="timeout",
            exit_code=None,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
        )
        return RunResult(
            run_id=run_id,
            status="timeout",
            exit_code=None,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
        )

    duration_ms = int((time.monotonic() - start) * 1000)
    status = "completed" if completed.returncode == 0 else "failed"
    storage.finish_run(
        run_id,
        status=status,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_ms=duration_ms,
    )
    return RunResult(
        run_id=run_id,
        status=status,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_ms=duration_ms,
    )


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def hidden_subprocess_kwargs() -> dict[str, int]:
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if not creation_flags:
        return {}
    return {"creationflags": creation_flags}


def normalize_run_inputs(action: Action, inputs: dict[str, str] | None = None) -> dict[str, str]:
    if not action.inputs_enabled:
        return {}
    supplied = inputs or {}
    normalized = {}
    supplied_by_lower = {str(key).lower(): value for key, value in supplied.items()}
    for name in action.input_names:
        value = supplied.get(name, supplied_by_lower.get(name.lower(), ""))
        normalized[name] = "" if value is None else str(value)
    for name in normalize_input_names([str(key) for key in supplied.keys()]):
        if name in normalized:
            continue
        value = supplied.get(name, supplied_by_lower.get(name.lower(), ""))
        normalized[name] = "" if value is None else str(value)
    return normalized


def build_env(action: Action, inputs: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    for name, value in normalize_run_inputs(action, inputs).items():
        env[f"COMMANDER_INPUT_{name.upper()}"] = value
    return env
