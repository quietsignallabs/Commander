from __future__ import annotations

import logging
import re
import uuid
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from commander.ai import CHATGPT_OAUTH_MODELS, complete_oauth, disconnect_openai, generate_action_draft, is_connected, list_chatgpt_models, start_oauth
from commander.client_encryption import client_encryption_base_url, ensure_client_certificate, generate_pairing_pin
from commander.executor import run_action
from commander.models import ActionInput, ValidationError
from commander.oauth_listener import ensure_oauth_listener, get_oauth_port_owner, is_commander_oauth_listener_available, stop_oauth_port_owner
from commander.paths import resource_path
from commander.storage import Storage


templates = Jinja2Templates(directory=str(resource_path("templates")))
templates.env.globals["asset_version"] = "2026-05-01-action-inputs"
logger = logging.getLogger(__name__)


def create_web_router(storage: Storage) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        base_url = f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}"
        return templates.TemplateResponse(
            request,
            "actions.html",
            {
                "actions": storage.list_actions(),
                "base_url": base_url,
                "settings": request.app.state.settings,
                "api_url_for": api_url_for,
                "curl_for": curl_for,
            },
        )

    @router.get("/actions/new", response_class=HTMLResponse)
    def new_action(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "action_form.html", {"action": None, "error": None, "script_text": ""})

    @router.get("/actions/ai", response_class=HTMLResponse)
    def new_ai_action(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "ai_action.html", {"error": None})

    @router.post("/actions/ai/generate", response_class=HTMLResponse)
    def generate_ai_action(request: Request, description: str = Form(...)) -> HTMLResponse:
        try:
            draft = generate_action_draft(request.app.state.settings, description.strip())
        except Exception as exc:
            return templates.TemplateResponse(
                request,
                "ai_action.html",
                {"error": str(exc), "description": description},
                status_code=400,
            )
        return templates.TemplateResponse(request, "ai_review.html", {"draft": draft})

    @router.post("/actions/ai/create")
    def create_ai_action(
        request: Request,
        name: str = Form(...),
        script: str = Form(...),
        timeout_seconds: int = Form(30),
        inputs_enabled: str | None = Form(None),
        input_names: str = Form(""),
    ) -> RedirectResponse:
        script_path = save_generated_script(request.app.state.settings.scripts_dir, name, script)
        storage.create_action(
            ActionInput(
                name=name,
                type="ps1",
                script_path=script_path,
                mode="wait",
                timeout_seconds=timeout_seconds,
                enabled=True,
                inputs_enabled=inputs_enabled == "on",
                input_names=parse_input_names(input_names) if inputs_enabled == "on" else [],
            )
        )
        return RedirectResponse("/", status_code=303)

    @router.post("/actions")
    async def create_action(
        request: Request,
        name: str = Form(...),
        type: str = Form(...),
        command: str = Form(""),
        mode: str = Form("wait"),
        timeout_seconds: int = Form(30),
        enabled: str | None = Form(None),
        inputs_enabled: str | None = Form(None),
        input_names: str = Form(""),
        script_text: str = Form(""),
        script_file: UploadFile | None = File(None),
    ) -> Response:
        return await _save_action(
            request,
            storage,
            original_name=None,
            name=name,
            type=type,
            command=command,
            mode=mode,
            timeout_seconds=timeout_seconds,
            enabled=enabled,
            inputs_enabled=inputs_enabled == "on",
            input_names=parse_input_names(input_names) if inputs_enabled == "on" else [],
            script_text=script_text,
            script_file=script_file,
        )

    @router.get("/actions/{name}/edit", response_class=HTMLResponse)
    def edit_action(request: Request, name: str) -> HTMLResponse:
        action = storage.get_action(name)
        if action is None:
            raise HTTPException(status_code=404, detail="Action not found")
        return templates.TemplateResponse(
            request,
            "action_form.html",
            {"action": action, "error": None, "script_text": load_script_text(action.script_path)},
        )

    @router.post("/actions/{name}")
    async def update_action(
        request: Request,
        name: str,
        new_name: str = Form(..., alias="name"),
        type: str = Form(...),
        command: str = Form(""),
        mode: str = Form("wait"),
        timeout_seconds: int = Form(30),
        enabled: str | None = Form(None),
        inputs_enabled: str | None = Form(None),
        input_names: str = Form(""),
        script_text: str = Form(""),
        script_file: UploadFile | None = File(None),
    ) -> Response:
        return await _save_action(
            request,
            storage,
            original_name=name,
            name=new_name,
            type=type,
            command=command,
            mode=mode,
            timeout_seconds=timeout_seconds,
            enabled=enabled,
            inputs_enabled=inputs_enabled == "on",
            input_names=parse_input_names(input_names) if inputs_enabled == "on" else [],
            script_text=script_text,
            script_file=script_file,
        )

    @router.post("/actions/{name}/delete")
    def delete_action(name: str) -> RedirectResponse:
        storage.delete_action(name)
        return RedirectResponse("/", status_code=303)

    @router.post("/actions/{name}/run")
    async def run_from_ui(request: Request, name: str) -> Response:
        action = storage.get_action(name)
        if action is None:
            raise HTTPException(status_code=404, detail="Action not found")
        if not action.enabled:
            raise HTTPException(status_code=400, detail="Action is disabled")
        inputs = await run_inputs_from_request(request)
        result = run_action(action, storage, inputs)
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"action_name": action.name, **asdict(result)})
        return RedirectResponse("/", status_code=303)

    @router.get("/history", response_class=HTMLResponse)
    def history(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "history.html", {"runs": storage.list_runs(limit=100)})

    @router.post("/history/clear")
    def clear_history() -> RedirectResponse:
        storage.clear_runs()
        return RedirectResponse("/history", status_code=303)

    @router.get("/settings", response_class=HTMLResponse)
    def settings(request: Request) -> HTMLResponse:
        app_settings = request.app.state.settings
        port_owner = get_oauth_port_owner()
        client_cert = ensure_client_certificate(app_settings)
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "settings": app_settings,
                "client_encryption_base_url": client_encryption_base_url(app_settings),
                "client_certificate_fingerprint": client_cert.fingerprint_sha256,
                "chatgpt_connected": is_connected(app_settings),
                "chatgpt_models": safe_chatgpt_models(app_settings),
                "oauth_ready": is_commander_oauth_listener_available(),
                "oauth_port_owner": port_owner,
            },
        )

    @router.post("/settings")
    def save_settings(
        request: Request,
        auth_enabled: str | None = Form(None),
        auth_token: str = Form(""),
        client_encryption_enabled: str | None = Form(None),
        client_encryption_port: int = Form(6768),
    ) -> RedirectResponse:
        app_settings = request.app.state.settings
        app_settings.auth_enabled = auth_enabled == "on"
        app_settings.auth_token = auth_token.strip()
        app_settings.client_encryption_enabled = client_encryption_enabled == "on"
        app_settings.client_encryption_port = client_encryption_port
        if app_settings.client_encryption_enabled:
            cert_info = ensure_client_certificate(app_settings)
            logger.info(
                "Client encryption settings saved: enabled=True port=%s fingerprint=%s restart_required=True",
                app_settings.client_encryption_port,
                cert_info.fingerprint_sha256,
            )
        else:
            logger.info("Client encryption settings saved: enabled=False port=%s", app_settings.client_encryption_port)
        app_settings.save_runtime_settings()
        return RedirectResponse("/settings", status_code=303)

    @router.post("/settings/client-encryption/pin")
    def create_client_pairing_pin(request: Request) -> RedirectResponse:
        app_settings = request.app.state.settings
        cert_info = ensure_client_certificate(app_settings)
        generate_pairing_pin(app_settings)
        logger.info(
            "Client pairing PIN generated: expires_at=%s port=%s fingerprint=%s",
            app_settings.client_pairing_pin_expires_at,
            app_settings.client_encryption_port,
            cert_info.fingerprint_sha256,
        )
        return RedirectResponse("/settings", status_code=303)

    @router.post("/settings/chatgpt/connect")
    def connect_chatgpt(request: Request) -> Response:
        if not ensure_oauth_listener(request.app):
            return templates.TemplateResponse(
                request,
                "oauth_conflict.html",
                {"oauth_port_owner": get_oauth_port_owner()},
                status_code=409,
            )
        return RedirectResponse(start_oauth(), status_code=303)

    @router.post("/settings/chatgpt/prepare")
    def prepare_chatgpt_oauth(request: Request) -> RedirectResponse:
        stop_oauth_port_owner()
        ensure_oauth_listener(request.app)
        return RedirectResponse("/settings", status_code=303)

    @router.post("/settings/chatgpt/model")
    def save_chatgpt_model(request: Request, openai_model: str = Form(...)) -> RedirectResponse:
        model = openai_model.strip()
        if model:
            app_settings = request.app.state.settings
            app_settings.openai_model = model
            app_settings.save_runtime_settings()
        return RedirectResponse("/settings", status_code=303)

    @router.post("/settings/chatgpt/disconnect")
    def disconnect_chatgpt(request: Request) -> RedirectResponse:
        disconnect_openai(request.app.state.settings)
        return RedirectResponse("/settings", status_code=303)

    @router.get("/auth/callback", response_class=HTMLResponse)
    def auth_callback(request: Request, code: str | None = None, state: str | None = None) -> HTMLResponse:
        if not code or not state:
            return HTMLResponse(_oauth_page("Missing code or state."), status_code=400)
        try:
            complete_oauth(request.app.state.settings, code, state)
        except Exception as exc:
            return HTMLResponse(_oauth_page(f"Error connecting ChatGPT: {exc}"), status_code=500)
        return HTMLResponse(_oauth_page("Connected to ChatGPT. You can close this tab and return to Commander."))

    @router.get("/auth/commander-health")
    def commander_oauth_health() -> Response:
        return Response("commander", media_type="text/plain")

    return router


def safe_chatgpt_models(settings) -> list[str]:
    try:
        return list_chatgpt_models(settings)
    except Exception:
        return CHATGPT_OAUTH_MODELS.copy()


async def _save_action(
    request: Request,
    storage: Storage,
    *,
    original_name: str | None,
    name: str,
    type: str,
    command: str,
    mode: str,
    timeout_seconds: int,
    enabled: str | None,
    inputs_enabled: bool,
    input_names: list[str],
    script_text: str,
    script_file: UploadFile | None,
) -> Response:
    script_path = None
    existing = storage.get_action(original_name) if original_name else None
    if type == "ps1":
        if script_file is not None and script_file.filename:
            script_path = await save_script_upload(request.app.state.settings.scripts_dir, script_file)
        elif script_text.strip():
            script_path = save_script_text(request.app.state.settings.scripts_dir, name, script_text, existing.script_path if existing else None)
        elif existing and existing.type == "ps1":
            script_path = existing.script_path
        else:
            raise HTTPException(status_code=400, detail="A PowerShell script or .ps1 file is required")

    try:
        action_input = ActionInput(
            name=name,
            type=type,
            command=command,
            script_path=script_path,
            mode=mode,
            timeout_seconds=timeout_seconds,
            enabled=enabled == "on",
            inputs_enabled=inputs_enabled,
            input_names=input_names,
        )
        if original_name:
            storage.update_action(original_name, action_input)
        else:
            storage.create_action(action_input)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "action_form.html",
            {"action": None, "error": str(exc), "script_text": script_text},
            status_code=400,
        )
    return RedirectResponse("/", status_code=303)


def parse_input_names(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[\n,]+", value or "") if part.strip()]


async def run_inputs_from_request(request: Request) -> dict[str, str]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        data = await request.json()
        if isinstance(data, dict) and isinstance(data.get("inputs"), dict):
            data = data["inputs"]
        if isinstance(data, dict):
            return {str(key): "" if value is None else str(value) for key, value in data.items()}
        return {}
    form = await request.form()
    return {
        key.removeprefix("input_"): str(value)
        for key, value in form.multi_items()
        if key.startswith("input_")
    }


async def save_script_upload(scripts_dir: Path, script_file: UploadFile | None) -> str:
    if script_file is None or not script_file.filename:
        raise HTTPException(status_code=400, detail="A .ps1 script file is required")
    original = Path(script_file.filename).name
    if Path(original).suffix.lower() != ".ps1":
        raise HTTPException(status_code=400, detail="Only .ps1 uploads are allowed")
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", Path(original).stem).strip("-") or "script"
    filename = f"{uuid.uuid4().hex}-{stem}.ps1"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    target = scripts_dir / filename
    target.write_bytes(await script_file.read())
    return str(target)


def save_generated_script(scripts_dir: Path, name: str, script: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "ai-action"
    target = scripts_dir / f"{uuid.uuid4().hex}-{stem}.ps1"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(script, encoding="utf-8")
    return str(target)


def load_script_text(script_path: str | None) -> str:
    if not script_path:
        return ""
    path = Path(script_path)
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def save_script_text(scripts_dir: Path, name: str, script: str, existing_script_path: str | None = None) -> str:
    if existing_script_path:
        target = Path(existing_script_path)
        target.parent.mkdir(parents=True, exist_ok=True)
    else:
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "script"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        target = scripts_dir / f"{uuid.uuid4().hex}-{stem}.ps1"
    target.write_text(script, encoding="utf-8")
    return str(target)


def _oauth_page(message: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Commander ChatGPT</title></head>
<body style="font-family:Segoe UI, sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#15181c;color:#e4e8ee">
  <main style="max-width:560px;text-align:center;padding:32px">
    <h1 style="margin:0 0 12px">Commander ChatGPT</h1>
    <p style="margin:0;color:#9aa4b2">{message}</p>
  </main>
</body>
</html>"""


def api_url_for(base_url: str, action_name: str) -> str:
    return f"{base_url}/api/actions/{quote(action_name, safe='')}/run"


def curl_for(
    base_url: str,
    action_name: str,
    auth_enabled: bool = False,
    auth_token: str | None = None,
    input_names: list[str] | None = None,
    inputs_enabled: bool = False,
) -> str:
    api_url = api_url_for(base_url, action_name)
    headers = []
    if auth_enabled and auth_token:
        headers.append(f'-H "X-Commander-Token: {auth_token}"')
    body = ""
    if inputs_enabled:
        headers.append('-H "Content-Type: application/json"')
        sample_names = input_names or ["message"]
        sample = ", ".join(f'\\"{name}\\":\\"value\\"' for name in sample_names)
        body = f' -d "{{\\"inputs\\":{{{sample}}}}}"'
    header_text = f" {' '.join(headers)}" if headers else ""
    return f'curl.exe -X POST{header_text}{body} "{api_url}"'
