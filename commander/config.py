import os
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    root_dir: Path = Path.cwd()
    host: str = "0.0.0.0"
    port: int = 6767
    auth_token: str | None = None
    auth_enabled: bool = False
    openai_auth: dict | None = None
    openai_model: str = "gpt-5.5"

    def __post_init__(self) -> None:
        self.root_dir = Path(self.root_dir)
        if self.auth_token is None:
            self.auth_token = os.environ.get("COMMANDER_API_TOKEN")
            self.auth_enabled = bool(self.auth_token)

    @property
    def data_dir(self) -> Path:
        return self.root_dir / "data"

    @property
    def scripts_dir(self) -> Path:
        return self.root_dir / "scripts"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "commander.db"

    @property
    def settings_path(self) -> Path:
        return self.data_dir / "settings.json"

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.scripts_dir.mkdir(parents=True, exist_ok=True)

    def load_runtime_settings(self) -> None:
        if not self.settings_path.exists():
            return
        data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        self.auth_enabled = bool(data.get("auth_enabled", False))
        self.auth_token = str(data.get("auth_token") or "")
        self.openai_auth = data.get("openai_auth")
        self.openai_model = _normalize_openai_model(str(data.get("openai_model") or self.openai_model))

    def save_runtime_settings(self) -> None:
        self.ensure_directories()
        self.settings_path.write_text(
            json.dumps(
                {
                    "auth_enabled": self.auth_enabled,
                    "auth_token": self.auth_token or "",
                    "openai_auth": self.openai_auth,
                    "openai_model": self.openai_model,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def _normalize_openai_model(model: str) -> str:
    if model == "gpt-5.4":
        return "gpt-5.5"
    return model
