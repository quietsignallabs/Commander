from __future__ import annotations

import csv
import io
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

import uvicorn


OAUTH_CALLBACK_PORT = 1455

_listener_lock = threading.Lock()
_listener_thread: threading.Thread | None = None


@dataclass(slots=True)
class PortOwner:
    pid: int
    name: str = ""
    path: str = ""


def start_oauth_listener(app: Any) -> None:
    global _listener_thread
    with _listener_lock:
        if is_commander_oauth_listener_available():
            return
        owner = get_oauth_port_owner()
        if owner is not None and owner.pid != os.getpid():
            return
        if _listener_thread is not None and _listener_thread.is_alive():
            return

        def run() -> None:
            uvicorn.run(app, host="0.0.0.0", port=OAUTH_CALLBACK_PORT, log_level="warning", log_config=None, access_log=False)

        _listener_thread = threading.Thread(target=run, daemon=True)
        _listener_thread.start()


def ensure_oauth_listener(app: Any, timeout_seconds: float = 2.0) -> bool:
    start_oauth_listener(app)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if is_commander_oauth_listener_available():
            return True
        time.sleep(0.1)
    return is_commander_oauth_listener_available()


def is_commander_oauth_listener_available() -> bool:
    try:
        req = UrlRequest("http://127.0.0.1:1455/auth/commander-health", headers={"User-Agent": "Commander"})
        with urlopen(req, timeout=1.0) as response:
            return response.read().decode("utf-8") == "commander"
    except Exception:
        return False


def get_oauth_port_owner() -> PortOwner | None:
    result = _run_hidden(["netstat", "-ano"])
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[1].endswith(":1455") and parts[3].upper() == "LISTENING":
            try:
                pid = int(parts[4])
            except ValueError:
                return None
            return _hydrate_owner(pid)
    return None


def stop_oauth_port_owner() -> None:
    owner = get_oauth_port_owner()
    if owner is None:
        return
    if owner.pid == os.getpid():
        return
    _run_hidden(["taskkill", "/PID", str(owner.pid), "/F"])


def _hydrate_owner(pid: int) -> PortOwner:
    try:
        result = _run_hidden(["wmic", "process", "where", f"ProcessId={pid}", "get", "Name,ExecutablePath", "/format:csv"])
    except FileNotFoundError:
        return PortOwner(pid=pid)
    if result.returncode == 0 and result.stdout.strip():
        rows = list(csv.DictReader(io.StringIO(result.stdout.strip())))
        if rows:
            row = rows[-1]
            return PortOwner(pid=pid, name=row.get("Name", "") or "", path=row.get("ExecutablePath", "") or "")
    return PortOwner(pid=pid)


def _run_hidden(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
