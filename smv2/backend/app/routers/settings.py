from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from app import config
from app.schemas import SettingsBootstrapOut, SettingsClearIn, SettingsOut, SettingsUpdateIn
from app.security.local_settings import csrf_token, require_local_settings_write
from app.services import llm_readiness_service
from app.services.local_settings_service import read_local_settings, write_local_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
def get_settings() -> SettingsOut:
    return SettingsOut.model_validate(_settings_payload())


@router.get("/bootstrap", response_model=SettingsBootstrapOut)
def bootstrap(response: Response) -> SettingsBootstrapOut:
    response.headers["Cache-Control"] = "no-store"
    return SettingsBootstrapOut.model_validate({"csrf_token": csrf_token(), "rollout": _rollout()})


@router.put("", response_model=SettingsOut)
def update_settings(body: SettingsUpdateIn, request: Request) -> SettingsOut:
    require_local_settings_write(request)
    current = read_local_settings(config.local_settings_path())
    if body.provider is not None:
        current["provider"] = body.provider
    if body.model is not None:
        current["model"] = body.model
    for key in ("anthropic_api_key", "ollama_base_url"):
        value = body.credentials.get(key)
        if value:
            current[key] = value
    write_local_settings(config.local_settings_path(), current)
    return SettingsOut.model_validate(_settings_payload())


@router.delete("", response_model=SettingsOut)
def clear_settings(body: SettingsClearIn, request: Request) -> SettingsOut:
    require_local_settings_write(request)
    expected = f"clear {body.provider} credential"
    if body.confirmation != expected:
        raise HTTPException(status_code=409, detail=f"confirmation must be {expected!r}")
    current = read_local_settings(config.local_settings_path())
    if body.provider == "anthropic":
        current.pop("anthropic_api_key", None)
    if body.provider == "ollama":
        current.pop("ollama_base_url", None)
    write_local_settings(config.local_settings_path(), current)
    return SettingsOut.model_validate(_settings_payload())


def _settings_payload() -> dict[str, Any]:
    local = read_local_settings(config.local_settings_path())
    anthropic_present = bool(config.anthropic_api_key())
    ollama_present = bool(config.ollama_base_url())
    credentials: dict[str, str] = {}
    if anthropic_present:
        credentials["anthropic_api_key"] = "[redacted]"
    if ollama_present:
        credentials["ollama_base_url"] = config.ollama_base_url()
    return {
        "provider": config.llm_provider(),
        "model": config.llm_model(),
        "credentials_present": {"anthropic": anthropic_present, "ollama": ollama_present},
        "credentials": credentials,
        "rollout": _rollout(),
        "readiness": llm_readiness_service.settings_summary(),
    }


def _rollout() -> dict[str, Any]:
    return {"local_settings_enabled": True}
