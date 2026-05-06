from __future__ import annotations

import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from commander.models import Action, ActionInput, RunRecord, ValidationError


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    type TEXT NOT NULL,
                    command TEXT,
                    script_path TEXT,
                    mode TEXT NOT NULL,
                    timeout_seconds INTEGER NOT NULL,
                    enabled INTEGER NOT NULL,
                    inputs_enabled INTEGER NOT NULL DEFAULT 0,
                    input_names TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(actions)").fetchall()}
            if "input_names" not in columns:
                conn.execute("ALTER TABLE actions ADD COLUMN input_names TEXT NOT NULL DEFAULT '[]'")
            if "inputs_enabled" not in columns:
                conn.execute("ALTER TABLE actions ADD COLUMN inputs_enabled INTEGER NOT NULL DEFAULT 0")
                conn.execute("UPDATE actions SET inputs_enabled = 1 WHERE input_names != '[]'")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_id INTEGER,
                    action_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    exit_code INTEGER,
                    stdout TEXT NOT NULL DEFAULT '',
                    stderr TEXT NOT NULL DEFAULT '',
                    duration_ms INTEGER,
                    FOREIGN KEY(action_id) REFERENCES actions(id) ON DELETE SET NULL
                )
                """
            )

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def create_action(self, action: ActionInput) -> Action:
        now = utc_now()
        try:
            with self.connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO actions
                    (name, type, command, script_path, mode, timeout_seconds, enabled, inputs_enabled, input_names, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        action.name,
                        action.type,
                        action.command,
                        action.script_path,
                        action.mode,
                        action.timeout_seconds,
                        int(action.enabled),
                        int(action.inputs_enabled),
                        json.dumps(action.input_names or []),
                        now,
                        now,
                    ),
                )
                row = conn.execute("SELECT * FROM actions WHERE id = ?", (cursor.lastrowid,)).fetchone()
        except sqlite3.IntegrityError as exc:
            raise ValidationError(f"Action '{action.name}' already exists") from exc
        return action_from_row(row)

    def update_action(self, name: str, action: ActionInput) -> Action:
        now = utc_now()
        try:
            with self.connect() as conn:
                cursor = conn.execute(
                    """
                    UPDATE actions
                    SET name = ?, type = ?, command = ?, script_path = ?, mode = ?,
                        timeout_seconds = ?, enabled = ?, inputs_enabled = ?, input_names = ?, updated_at = ?
                    WHERE name = ? COLLATE NOCASE
                    """,
                    (
                        action.name,
                        action.type,
                        action.command,
                        action.script_path,
                        action.mode,
                        action.timeout_seconds,
                        int(action.enabled),
                        int(action.inputs_enabled),
                        json.dumps(action.input_names or []),
                        now,
                        name,
                    ),
                )
                if cursor.rowcount == 0:
                    raise ValidationError(f"Action '{name}' was not found")
                row = conn.execute("SELECT * FROM actions WHERE name = ? COLLATE NOCASE", (action.name,)).fetchone()
        except sqlite3.IntegrityError as exc:
            raise ValidationError(f"Action '{action.name}' already exists") from exc
        return action_from_row(row)

    def list_actions(self) -> list[Action]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM actions ORDER BY name COLLATE NOCASE").fetchall()
        return [action_from_row(row) for row in rows]

    def get_action(self, name: str) -> Action | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM actions WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
        return action_from_row(row) if row else None

    def delete_action(self, name: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM actions WHERE name = ? COLLATE NOCASE", (name,))

    def create_run(self, action_id: int | None, action_name: str, status: str) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO runs (action_id, action_name, status, started_at) VALUES (?, ?, ?, ?)",
                (action_id, action_name, status, utc_now()),
            )
            return int(cursor.lastrowid)

    def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        exit_code: int | None,
        stdout: str,
        stderr: str,
        duration_ms: int | None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE runs
                SET status = ?, finished_at = ?, exit_code = ?, stdout = ?, stderr = ?, duration_ms = ?
                WHERE id = ?
                """,
                (status, utc_now(), exit_code, stdout, stderr, duration_ms, run_id),
            )

    def list_runs(self, limit: int = 100) -> list[RunRecord]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [run_from_row(row) for row in rows]

    def clear_runs(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM runs")


def action_from_row(row: sqlite3.Row) -> Action:
    data: dict[str, Any] = dict(row)
    data["enabled"] = bool(data["enabled"])
    data["inputs_enabled"] = bool(data.get("inputs_enabled", False))
    data["input_names"] = json.loads(data.get("input_names") or "[]")
    return Action(**data)


def run_from_row(row: sqlite3.Row) -> RunRecord:
    return RunRecord(**dict(row))
