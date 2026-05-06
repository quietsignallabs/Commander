from __future__ import annotations

from dataclasses import dataclass
import re


ACTION_TYPES = {"cmd", "powershell", "ps1"}
RUN_MODES = {"wait", "start"}
RUN_STATUSES = {"running", "completed", "failed", "timeout"}


class ValidationError(ValueError):
    pass


@dataclass(slots=True)
class ActionInput:
    name: str
    type: str
    command: str | None = None
    script_path: str | None = None
    mode: str = "wait"
    timeout_seconds: int = 30
    enabled: bool = True
    inputs_enabled: bool = False
    input_names: list[str] | None = None

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        self.type = self.type.strip().lower()
        self.mode = self.mode.strip().lower()
        if self.command is not None:
            self.command = self.command.strip()
        if self.script_path is not None:
            self.script_path = self.script_path.strip()
        self.input_names = normalize_input_names(self.input_names or [])
        validate_action_input(self)


@dataclass(slots=True)
class Action:
    id: int
    name: str
    type: str
    command: str | None
    script_path: str | None
    mode: str
    timeout_seconds: int
    enabled: bool
    inputs_enabled: bool
    input_names: list[str]
    created_at: str
    updated_at: str


@dataclass(slots=True)
class RunRecord:
    id: int
    action_id: int | None
    action_name: str
    status: str
    started_at: str
    finished_at: str | None
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int | None


def validate_action_input(action: ActionInput) -> None:
    if not action.name:
        raise ValidationError("Action name is required")
    if action.type not in ACTION_TYPES:
        raise ValidationError("Action type must be cmd, powershell, or ps1")
    if action.mode not in RUN_MODES:
        raise ValidationError("Action mode must be wait or start")
    if action.timeout_seconds < 1 or action.timeout_seconds > 3600:
        raise ValidationError("Action timeout must be between 1 and 3600 seconds")
    if action.type in {"cmd", "powershell"} and not action.command:
        raise ValidationError("Action command is required")
    if action.type == "ps1" and not action.script_path:
        raise ValidationError("Action script path is required")
    for input_name in action.input_names or []:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", input_name):
            raise ValidationError("Action input names must start with a letter or underscore and contain only letters, numbers, or underscores")


def normalize_input_names(input_names: list[str]) -> list[str]:
    normalized = []
    seen = set()
    for input_name in input_names:
        value = str(input_name).strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(value)
    return normalized
