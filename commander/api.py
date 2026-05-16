from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastapi import Body, FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from commander.ai import generate_action_draft
from commander.client_encryption import client_encryption_base_url, ensure_client_certificate, pairing_pin_is_valid
from commander.config import Settings
from commander.executor import run_action
from commander.models import ActionInput, ValidationError
from commander.paths import resource_path
from commander.storage import Storage
from commander.web import create_web_router, load_script_text, save_generated_script, save_script_text


logger = logging.getLogger(__name__)


class ActionPayload(BaseModel):
    name: str
    type: str
    command: str | None = None
    script_path: str | None = None
    script_text: str | None = None
    mode: str = "wait"
    timeout_seconds: int = 30
    enabled: bool = True
    inputs_enabled: bool = False
    input_names: list[str] = []


class ActionEditPayload(BaseModel):
    name: str | None = None
    type: str | None = None
    command: str | None = None
    script_path: str | None = None
    script_text: str | None = None
    mode: str | None = None
    timeout_seconds: int | None = None
    enabled: bool | None = None
    inputs_enabled: bool | None = None
    input_names: list[str] | None = None


class AIActionPayload(BaseModel):
    description: str


class ClientPairingPayload(BaseModel):
    pin: str


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.ensure_directories()
    settings.load_runtime_settings()
    storage = Storage(settings.db_path)
    storage.initialize()

    app = FastAPI(title="Commander", version="0.1.0")
    app.state.settings = settings
    app.state.storage = storage

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        if request.url.path == "/api/client-encryption/pair":
            logger.warning(
                "Client pairing validation failed: scheme=%s client=%s content_type=%s content_length=%s missing_fields=%s errors=%s",
                request.url.scheme,
                request.client.host if request.client else "unknown",
                request.headers.get("content-type", ""),
                request.headers.get("content-length", ""),
                _missing_validation_fields(exc),
                _validation_error_types(exc),
            )
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    app.mount("/static", StaticFiles(directory=str(resource_path("static"))), name="static")
    app.include_router(create_web_router(storage))

    @app.get("/api/actions")
    def list_actions(x_commander_token: str | None = Header(None)) -> list[dict[str, Any]]:
        require_api_token(settings, x_commander_token)
        return [asdict(action) for action in storage.list_actions()]

    @app.post("/api/actions", status_code=201)
    def create_action(payload: ActionPayload, x_commander_token: str | None = Header(None)) -> dict[str, Any]:
        require_api_token(settings, x_commander_token)
        try:
            action = storage.create_action(action_input_from_payload(settings, payload))
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(action)

    @app.get("/api/actions/{name}")
    def get_action(name: str, x_commander_token: str | None = Header(None)) -> dict[str, Any]:
        require_api_token(settings, x_commander_token)
        action = storage.get_action(name)
        if action is None:
            raise HTTPException(status_code=404, detail="Action not found")
        return asdict(action)

    @app.get("/api/actions/{name}/script")
    def get_action_script(name: str, x_commander_token: str | None = Header(None)) -> dict[str, Any]:
        require_api_token(settings, x_commander_token)
        action = storage.get_action(name)
        if action is None:
            raise HTTPException(status_code=404, detail="Action not found")
        if action.type != "ps1":
            raise HTTPException(status_code=400, detail="Action is not a ps1 script action")
        return {
            "name": action.name,
            "script_path": action.script_path,
            "script_text": load_script_text(action.script_path),
        }

    @app.put("/api/actions/{name}")
    def update_action(name: str, payload: ActionPayload, x_commander_token: str | None = Header(None)) -> dict[str, Any]:
        require_api_token(settings, x_commander_token)
        try:
            action = storage.update_action(name, action_input_from_payload(settings, payload, storage.get_action(name)))
        except ValidationError as exc:
            status = 404 if "not found" in str(exc) else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        return asdict(action)

    @app.patch("/api/actions/{name}")
    def edit_action(name: str, payload: ActionEditPayload, x_commander_token: str | None = Header(None)) -> dict[str, Any]:
        require_api_token(settings, x_commander_token)
        existing = storage.get_action(name)
        if existing is None:
            raise HTTPException(status_code=404, detail="Action not found")
        try:
            merged_payload = merge_action_edit(existing, payload)
            action = storage.update_action(name, action_input_from_payload(settings, merged_payload, existing))
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(action)

    @app.delete("/api/actions/{name}", status_code=204)
    def delete_action(name: str, x_commander_token: str | None = Header(None)) -> Response:
        require_api_token(settings, x_commander_token)
        storage.delete_action(name)
        return Response(status_code=204)

    @app.post("/api/actions/{name}/run")
    def run_saved_action(name: str, payload: dict[str, Any] | None = Body(None), x_commander_token: str | None = Header(None)) -> dict[str, Any]:
        require_api_token(settings, x_commander_token)
        action = storage.get_action(name)
        if action is None:
            raise HTTPException(status_code=404, detail="Action not found")
        if not action.enabled:
            raise HTTPException(status_code=400, detail="Action is disabled")
        return asdict(run_action(action, storage, inputs_from_payload(payload)))

    @app.post("/api/ai/actions/draft")
    def draft_ai_action(payload: AIActionPayload, x_commander_token: str | None = Header(None)) -> dict[str, Any]:
        require_api_token(settings, x_commander_token)
        description = payload.description.strip()
        if not description:
            raise HTTPException(status_code=400, detail="Description is required")
        try:
            return asdict(generate_action_draft(settings, description))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/ai/actions", status_code=201)
    def create_ai_action(payload: AIActionPayload, x_commander_token: str | None = Header(None)) -> dict[str, Any]:
        require_api_token(settings, x_commander_token)
        description = payload.description.strip()
        if not description:
            raise HTTPException(status_code=400, detail="Description is required")
        try:
            draft = generate_action_draft(settings, description)
            script_path = save_generated_script(settings.scripts_dir, draft.name, draft.script)
            action = storage.create_action(
                ActionInput(
                    name=draft.name,
                    type="ps1",
                    script_path=script_path,
                    mode="wait",
                    timeout_seconds=draft.timeout_seconds,
                    enabled=True,
                    inputs_enabled=draft.inputs_enabled,
                    input_names=draft.input_names or [],
                )
            )
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(action)

    @app.get("/api/runs")
    def list_runs(x_commander_token: str | None = Header(None)) -> list[dict[str, Any]]:
        require_api_token(settings, x_commander_token)
        return [asdict(run) for run in storage.list_runs()]

    @app.get("/api/client-encryption/info")
    def client_encryption_info() -> dict[str, Any]:
        cert_info = ensure_client_certificate(settings)
        logger.info(
            "Client encryption info requested: enabled=%s port=%s scheme=https fingerprint=%s",
            settings.client_encryption_enabled,
            settings.client_encryption_port,
            cert_info.fingerprint_sha256,
        )
        return {
            "enabled": settings.client_encryption_enabled,
            "port": settings.client_encryption_port,
            "base_url": client_encryption_base_url(settings),
            "certificate_fingerprint_sha256": cert_info.fingerprint_sha256,
        }

    @app.post("/api/client-encryption/pair")
    def pair_client(request: Request, payload: ClientPairingPayload) -> dict[str, Any]:
        logger.info(
            "Client pairing attempt: scheme=%s client=%s content_type=%s has_pin=%s",
            request.url.scheme,
            request.client.host if request.client else "unknown",
            request.headers.get("content-type", ""),
            bool(payload.pin.strip()),
        )
        if not settings.client_encryption_enabled:
            logger.warning("Client pairing rejected: reason=client_encryption_disabled scheme=%s", request.url.scheme)
            raise HTTPException(status_code=400, detail="Client encryption is not enabled")
        if request.url.scheme != "https":
            logger.warning("Client pairing rejected: reason=plain_http client=%s", request.client.host if request.client else "unknown")
            raise HTTPException(status_code=400, detail="Pairing must be completed over HTTPS")
        if not pairing_pin_is_valid(settings, payload.pin.strip()):
            logger.warning(
                "Client pairing rejected: reason=invalid_or_expired_pin client=%s pin_configured=%s expires_at=%s",
                request.client.host if request.client else "unknown",
                bool(settings.client_pairing_pin),
                settings.client_pairing_pin_expires_at or "",
            )
            raise HTTPException(status_code=401, detail="Invalid or expired pairing PIN")
        cert_info = ensure_client_certificate(settings)
        settings.client_pairing_pin = None
        settings.client_pairing_pin_expires_at = None
        settings.save_runtime_settings()
        logger.info(
            "Client pairing succeeded: client=%s port=%s fingerprint=%s",
            request.client.host if request.client else "unknown",
            settings.client_encryption_port,
            cert_info.fingerprint_sha256,
        )
        return {
            "base_url": client_encryption_base_url(settings),
            "certificate_fingerprint_sha256": cert_info.fingerprint_sha256,
        }

    return app


def _missing_validation_fields(exc: RequestValidationError) -> str:
    fields = []
    for error in exc.errors():
        if error.get("type") == "missing":
            location = ".".join(str(part) for part in error.get("loc", ()))
            fields.append(location)
    return ",".join(fields) if fields else "none"


def _validation_error_types(exc: RequestValidationError) -> str:
    return ",".join(str(error.get("type", "unknown")) for error in exc.errors())


def action_input_from_payload(settings: Settings, payload: ActionPayload, existing_action=None) -> ActionInput:
    data = payload.model_dump(exclude={"script_text"})
    action_type = str(data.get("type", "")).strip().lower()
    script_text = (payload.script_text or "").strip()

    if action_type == "ps1":
        if script_text:
            data["script_path"] = save_script_text(
                settings.scripts_dir,
                payload.name,
                payload.script_text or "",
                existing_action.script_path if existing_action and existing_action.type == "ps1" else None,
            )
        elif not data.get("script_path") and existing_action and existing_action.type == "ps1":
            data["script_path"] = existing_action.script_path

    return ActionInput(**data)


def merge_action_edit(existing_action, payload: ActionEditPayload) -> ActionPayload:
    data = {
        "name": existing_action.name,
        "type": existing_action.type,
        "command": existing_action.command,
        "script_path": existing_action.script_path,
        "mode": existing_action.mode,
        "timeout_seconds": existing_action.timeout_seconds,
        "enabled": existing_action.enabled,
        "inputs_enabled": existing_action.inputs_enabled,
        "input_names": existing_action.input_names,
    }
    data.update(payload.model_dump(exclude_unset=True))
    return ActionPayload(**data)


def require_api_token(settings: Settings, supplied_token: str | None) -> None:
    if not settings.auth_enabled:
        return
    if not settings.auth_token or supplied_token != settings.auth_token:
        raise HTTPException(status_code=401, detail="Invalid or missing Commander API token")


def inputs_from_payload(payload: dict[str, Any] | None) -> dict[str, str]:
    if not payload:
        return {}
    if isinstance(payload.get("inputs"), dict):
        payload = payload["inputs"]
    return {str(key): "" if value is None else str(value) for key, value in payload.items()}
