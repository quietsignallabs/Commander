import os
import json
from dataclasses import dataclass
from pathlib import Path


DEFAULT_API_TOKEN = "1234567890"


@dataclass(slots=True)
class Settings:
    root_dir: Path = Path.cwd()
    host: str = "0.0.0.0"
    port: int = 6767
    auth_token: str | None = None
    auth_enabled: bool = True
    client_encryption_enabled: bool = True
    client_encryption_port: int = 6768
    client_pairing_pin: str | None = None
    client_pairing_pin_expires_at: str | None = None
    openai_auth: dict | None = None
    openai_model: str = "gpt-5.5"

    def __post_init__(self) -> None:
        self.root_dir = Path(self.root_dir)
        if self.auth_token is None:
            self.auth_token = os.environ.get("COMMANDER_API_TOKEN") or DEFAULT_API_TOKEN

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

    @property
    def client_tls_cert_path(self) -> Path:
        return self.data_dir / "client-encryption-cert.pem"

    @property
    def client_tls_key_path(self) -> Path:
        return self.data_dir / "client-encryption-key.pem"

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.scripts_dir.mkdir(parents=True, exist_ok=True)

    def load_runtime_settings(self) -> None:
        if not self.settings_path.exists():
            return
        data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        self.auth_enabled = bool(data.get("auth_enabled", self.auth_enabled))
        self.auth_token = str(data.get("auth_token") or self.auth_token or DEFAULT_API_TOKEN)
        self.client_encryption_enabled = bool(data.get("client_encryption_enabled", self.client_encryption_enabled))
        self.client_encryption_port = int(data.get("client_encryption_port") or self.client_encryption_port)
        self.client_pairing_pin = data.get("client_pairing_pin")
        self.client_pairing_pin_expires_at = data.get("client_pairing_pin_expires_at")
        self.openai_auth = data.get("openai_auth")
        self.openai_model = _normalize_openai_model(str(data.get("openai_model") or self.openai_model))

    def save_runtime_settings(self) -> None:
        self.ensure_directories()
        self.settings_path.write_text(
            json.dumps(
                {
                    "auth_enabled": self.auth_enabled,
                    "auth_token": self.auth_token or "",
                    "client_encryption_enabled": self.client_encryption_enabled,
                    "client_encryption_port": self.client_encryption_port,
                    "client_pairing_pin": self.client_pairing_pin,
                    "client_pairing_pin_expires_at": self.client_pairing_pin_expires_at,
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
