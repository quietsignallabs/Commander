from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from threading import Lock
from urllib.parse import urlencode

import requests

from commander.config import Settings
from commander.models import normalize_input_names

try:
    import codex_auth  # noqa: F401  # Must be imported before openai when available.
    from openai import OpenAI
except Exception:  # pragma: no cover - exercised only when optional deps are absent.
    OpenAI = None


OPENAI_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_REDIRECT_URI = "http://localhost:1455/auth/callback"
OPENAI_AUTH_URL = "https://auth.openai.com/oauth/authorize"
OPENAI_TOKEN_URL = "https://auth.openai.com/oauth/token"
OPENAI_SCOPE = "openid profile email offline_access"
OPENAI_MODEL = "gpt-5.5"
CHATGPT_OAUTH_MODELS = [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.2",
]

_oauth_pending: dict[str, dict[str, str]] = {}
_oauth_lock = Lock()
_chatgpt_lock = Lock()


@dataclass(slots=True)
class ActionDraft:
    name: str
    script: str
    explanation: str
    timeout_seconds: int = 30
    inputs_enabled: bool = False
    input_names: list[str] | None = None


def generate_pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


def start_oauth() -> str:
    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(16)
    with _oauth_lock:
        _oauth_pending[state] = {"verifier": verifier}
    params = {
        "response_type": "code",
        "client_id": OPENAI_CLIENT_ID,
        "redirect_uri": OPENAI_REDIRECT_URI,
        "scope": OPENAI_SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
    }
    return f"{OPENAI_AUTH_URL}?{urlencode(params)}"


def complete_oauth(settings: Settings, code: str, state: str) -> None:
    with _oauth_lock:
        pending = _oauth_pending.get(state)
    if not pending:
        raise ValueError("Invalid or expired OAuth state")

    response = requests.post(
        OPENAI_TOKEN_URL,
        json={
            "grant_type": "authorization_code",
            "client_id": OPENAI_CLIENT_ID,
            "code": code,
            "redirect_uri": OPENAI_REDIRECT_URI,
            "code_verifier": pending["verifier"],
        },
        timeout=30,
    )
    response.raise_for_status()
    token_data = response.json()
    settings.openai_auth = _auth_from_token_data(token_data)
    settings.save_runtime_settings()
    with _oauth_lock:
        _oauth_pending.pop(state, None)


def disconnect_openai(settings: Settings) -> None:
    settings.openai_auth = None
    settings.save_runtime_settings()


def is_connected(settings: Settings) -> bool:
    return bool(settings.openai_auth and settings.openai_auth.get("access_token"))


def get_openai_access_token(settings: Settings) -> str | None:
    openai_auth = settings.openai_auth
    if not openai_auth or not openai_auth.get("access_token"):
        return None
    if time.time() <= float(openai_auth.get("expires", 0)) - 300:
        return str(openai_auth["access_token"])
    refresh_token = openai_auth.get("refresh_token")
    if not refresh_token:
        return None

    response = requests.post(
        OPENAI_TOKEN_URL,
        json={
            "grant_type": "refresh_token",
            "client_id": OPENAI_CLIENT_ID,
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    response.raise_for_status()
    token_data = response.json()
    openai_auth.update(_auth_from_token_data(token_data))
    settings.openai_auth = openai_auth
    settings.save_runtime_settings()
    return str(openai_auth["access_token"])


def generate_action_draft(settings: Settings, description: str) -> ActionDraft:
    text = chatgpt(settings, build_action_prompt(description), max_tokens=1800)
    try:
        data = json.loads(extract_json(text))
    except json.JSONDecodeError as exc:
        fallback = draft_from_non_json(text, description)
        if fallback is None:
            log_ai_parse_failure(settings, text)
            raise ValueError("ChatGPT returned an unexpected format. Please try again.") from exc
        return fallback

    name = str(data.get("name", "")).strip()
    script = normalize_script_text(str(data.get("script", "")).strip())
    explanation = str(data.get("explanation", "")).strip()
    timeout_seconds = int(data.get("timeout_seconds", 30))
    input_names = normalize_input_names([str(name) for name in data.get("input_names", [])])
    inputs_enabled = bool(data.get("inputs_enabled", False) or input_names)
    if not name or not script:
        raise ValueError("ChatGPT did not return an action name and script.")
    return ActionDraft(
        name=name[:120],
        script=f"{script}\n",
        explanation=explanation or "Generated PowerShell action.",
        timeout_seconds=max(1, min(timeout_seconds, 3600)),
        inputs_enabled=inputs_enabled,
        input_names=input_names,
    )


def list_chatgpt_models(settings: Settings) -> list[str]:
    return CHATGPT_OAUTH_MODELS.copy()


def draft_from_non_json(text: str, description: str) -> ActionDraft | None:
    script = normalize_script_text(extract_fenced_powershell(text))
    if not script:
        return None
    name_match = re.search(r"(?im)^\s*(?:action\s*)?name\s*:\s*(.+)$", text)
    name = name_match.group(1).strip() if name_match else title_from_description(description)
    explanation = extract_explanation(text, script)
    return ActionDraft(
        name=name[:120],
        script=f"{script.strip()}\n",
        explanation=explanation or "Generated PowerShell action.",
        timeout_seconds=30,
        inputs_enabled=False,
        input_names=[],
    )


def normalize_script_text(script: str) -> str:
    if "\n" not in script and ("\\n" in script or "\\r\\n" in script):
        return script.replace("\\r\\n", "\n").replace("\\n", "\n")
    return script


def extract_fenced_powershell(text: str) -> str:
    match = re.search(r"```(?:powershell|ps1|pwsh)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def extract_explanation(text: str, script: str) -> str:
    without_script = text.replace(script, "")
    without_fences = re.sub(r"```.*?```", "", without_script, flags=re.DOTALL).strip()
    lines = [
        line.strip()
        for line in without_fences.splitlines()
        if line.strip() and not re.match(r"(?i)^(?:action\s*)?name\s*:", line.strip())
    ]
    return lines[0] if lines else ""


def title_from_description(description: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", description)[:6]
    return " ".join(word.capitalize() for word in words) or "AI Generated Action"


def log_ai_parse_failure(settings: Settings, text: str) -> None:
    try:
        settings.ensure_directories()
        log_path = settings.data_dir / "ai_parse_error.log"
        log_path.write_text(text, encoding="utf-8")
    except Exception:
        pass


def chatgpt(settings: Settings, prompt: str, max_tokens: int = 1024) -> str:
    access_token = get_openai_access_token(settings)
    if not access_token:
        raise ValueError("Not connected to ChatGPT. Connect ChatGPT in Settings.")
    if OpenAI is None:
        raise ValueError("OpenAI dependencies are not installed. Install requirements.txt and restart.")

    with _chatgpt_lock:
        os.environ["CODEX_AUTH_TOKEN"] = access_token
        try:
            client = OpenAI()
            raw = ""
            errors: list[str] = []

            try:
                parts: list[str] = []
                final_response = None
                with client.responses.stream(
                    model=settings.openai_model,
                    input=prompt,
                    store=False,
                ) as stream:
                    for event in stream:
                        event_type = getattr(event, "type", "")
                        if event_type == "response.output_text.delta" and getattr(event, "delta", ""):
                            parts.append(event.delta)
                        elif event_type == "response.output_text.done" and getattr(event, "text", "") and not parts:
                            parts.append(event.text)
                        elif event_type == "response.completed":
                            final_response = getattr(event, "response", None)
                        elif event_type == "response.failed":
                            raise ValueError(f"Responses stream failed: {getattr(event, 'response', None)}")
                raw = "".join(parts).strip()
                if not raw and final_response is not None:
                    raw = extract_openai_text(final_response)
            except Exception as exc:
                errors.append(f"streamed Responses API: {exc}")

            if not raw:
                try:
                    response = client.responses.create(
                        model=settings.openai_model,
                        input=prompt,
                        store=False,
                    )
                    raw = extract_openai_text(response)
                except Exception as exc:
                    errors.append(f"Responses API: {exc}")

            if not raw:
                try:
                    chat_response = client.chat.completions.create(
                        model=settings.openai_model,
                        messages=[{"role": "user", "content": prompt}],
                        store=False,
                    )
                    if chat_response.choices:
                        raw = extract_openai_text(chat_response.choices[0].message)
                except Exception as exc:
                    errors.append(f"Chat Completions API: {exc}")

            if not raw and errors:
                raise ValueError("AI request returned no text. " + " | ".join(errors))
            return raw.strip()
        finally:
            os.environ.pop("CODEX_AUTH_TOKEN", None)


def build_action_prompt(description: str) -> str:
    return f"""
You create Windows PowerShell scripts for a local automation tool named Commander.

User request:
{description}

Return only a JSON object with these fields:
{{
  "name": "short action name",
  "script": "PowerShell script text",
  "explanation": "one sentence explanation",
  "timeout_seconds": 30,
  "inputs_enabled": false,
  "input_names": []
}}

Example response shape:
{{
  "name": "Show Current User",
  "script": "# Show current Windows identity\\nWrite-Output ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)",
  "explanation": "Shows the Windows account running Commander.",
  "timeout_seconds": 30,
  "inputs_enabled": false,
  "input_names": []
}}

Example response shape with runtime input:
{{
  "name": "Say Message",
  "script": "param([string]$message)\\n# Print the supplied message\\nWrite-Output $message",
  "explanation": "Prints a message supplied when the action runs.",
  "timeout_seconds": 30,
  "inputs_enabled": true,
  "input_names": ["message"]
}}

Rules:
- Generate PowerShell only.
- If the user asks for a value that should be supplied when the action runs, set inputs_enabled to true and add helpful input names.
- Input names must use only letters, numbers, and underscores, and must start with a letter.
- Runtime inputs are available as PowerShell parameters for .ps1 actions, such as param([string]$message), and as environment variables such as $env:COMMANDER_INPUT_MESSAGE.
- Your entire response must be parseable JSON.
- Escape newlines in the script field as \\n.
- Do not include markdown fences.
- Include short comments for major script steps.
- Do not exfiltrate credentials, tokens, browser data, SSH keys, or private files.
- Do not upload data to the internet.
- Do not include destructive commands unless the user explicitly requested destructive behavior.
- Prefer commands that are safe to run repeatedly.
""".strip()


def extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0].strip()
    for start_ch, end_ch in (("{", "}"),):
        start = text.find(start_ch)
        if start == -1:
            continue
        depth = 0
        in_str = False
        escape = False
        for index, char in enumerate(text[start:], start):
            if escape:
                escape = False
                continue
            if char == "\\" and in_str:
                escape = True
                continue
            if char == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if char == start_ch:
                depth += 1
            elif char == end_ch:
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
    return text


def extract_openai_text(payload) -> str:
    seen: set[int] = set()

    def walk(value) -> str:
        if value is None:
            return ""
        value_id = id(value)
        if value_id in seen:
            return ""
        seen.add(value_id)

        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return "\n".join(filter(None, (walk(item) for item in value))).strip()
        if isinstance(value, dict):
            for key in ("output_text", "text", "content", "output", "message"):
                text = walk(value.get(key))
                if text:
                    return text
            return ""

        for attr in ("output_text", "text", "content", "output", "message"):
            if hasattr(value, attr):
                text = walk(getattr(value, attr))
                if text:
                    return text

        if hasattr(value, "model_dump"):
            try:
                dumped = value.model_dump()
            except Exception:
                dumped = None
            if dumped:
                return walk(dumped)
        return ""

    return walk(payload).strip()


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _auth_from_token_data(token_data: dict) -> dict:
    id_token = token_data.get("id_token", "")
    return {
        "access_token": token_data["access_token"],
        "refresh_token": token_data.get("refresh_token", ""),
        "expires": time.time() + token_data.get("expires_in", 3600),
        "account_id": _account_id_from_id_token(id_token),
        "id_token": id_token,
    }


def _account_id_from_id_token(id_token: str) -> str:
    if not id_token:
        return ""
    try:
        payload = id_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return str(claims.get("sub", ""))
    except Exception:
        return ""
