from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

from app import config
from app.schemas import (
    OllamaModelsDiscoverIn,
    OllamaModelsDiscoverOut,
    SettingsBootstrapOut,
    SettingsClearIn,
    SettingsOut,
    SettingsUpdateIn,
)
from app.security.local_settings import (
    csrf_token,
    normalize_ollama_base_url,
    require_local_settings_write,
)
from app.services import llm_readiness_service
from app.services import local_settings_service
from app.llm.ollama_discovery_service import (
    OllamaDiscoveryError,
    discover_ollama_models,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
def get_settings() -> SettingsOut:
    return SettingsOut.model_validate(_settings_payload())


@router.get("/bootstrap", response_model=SettingsBootstrapOut)
def bootstrap(response: Response) -> SettingsBootstrapOut:
    response.headers["Cache-Control"] = "no-store"
    return SettingsBootstrapOut.model_validate(
        {"csrf_token": csrf_token(), "rollout": _rollout()}
    )


@router.put("", response_model=SettingsOut)
async def update_settings(
    body: SettingsUpdateIn, request: Request, response: Response
) -> SettingsOut:
    require_local_settings_write(request)
    current = local_settings_service.read_local_settings(config.local_settings_path())
    secrets = local_settings_service.read_local_settings(config.secrets_path())

    next_settings = dict(current)
    if body.provider is not None:
        next_settings["provider"] = body.provider
    if body.model is not None:
        next_settings["model"] = body.model
    if body.curriculum_provider is not None:
        next_settings["curriculum_provider"] = body.curriculum_provider
    if body.curriculum_model is not None:
        next_settings["curriculum_model"] = body.curriculum_model

    next_secrets = dict(secrets)
    for key in ("anthropic_api_key", "ollama_base_url", "deepseek_api_key", "gemini_api_key"):
        value = body.credentials.get(key)
        if value:
            next_secrets[key] = value

    provider = (
        next_settings.get("provider")
        if isinstance(next_settings.get("provider"), str)
        else None
    )
    model = (
        next_settings.get("model")
        if isinstance(next_settings.get("model"), str)
        else None
    )
    if provider == "ollama":
        submitted_url = body.credentials.get("ollama_base_url")
        normalized_url = _resolve_ollama_base_url(submitted_url)
        models = await _discover_ollama_models_or_http_error(normalized_url)
        if model not in models:
            raise HTTPException(
                status_code=409,
                detail=_ollama_error_detail(
                    "ollama_model_unavailable",
                    "ollama_model_unavailable",
                    "The selected Ollama model is not available from the configured server.",
                ),
            )
        next_secrets["ollama_base_url"] = normalized_url

    if body.credentials:
        local_settings_service.write_local_settings_pair(
            config.local_settings_path(),
            next_settings,
            config.secrets_path(),
            next_secrets,
        )
    else:
        local_settings_service.write_local_settings(
            config.local_settings_path(), next_settings
        )
    response.headers["Cache-Control"] = "no-store"
    return SettingsOut.model_validate(_settings_payload())


@router.post("/ollama/models", response_model=OllamaModelsDiscoverOut)
async def discover_models(
    body: OllamaModelsDiscoverIn, request: Request, response: Response
) -> OllamaModelsDiscoverOut:
    require_local_settings_write(request)
    base_url = _resolve_ollama_base_url(body.base_url)
    models = await _discover_ollama_models_or_http_error(base_url)
    response.headers["Cache-Control"] = "no-store"
    configured_model = body.configured_model
    return OllamaModelsDiscoverOut(
        models=models,
        configured_model=configured_model,
        configured_model_available=configured_model in models
        if configured_model
        else False,
    )


@router.delete("", response_model=SettingsOut)
def clear_settings(
    body: SettingsClearIn, request: Request, response: Response
) -> SettingsOut:
    require_local_settings_write(request)
    expected = f"clear {body.provider} credential"
    if body.confirmation != expected:
        raise HTTPException(
            status_code=409, detail=f"confirmation must be {expected!r}"
        )
    secrets = local_settings_service.read_local_settings(config.secrets_path())
    if body.provider == "anthropic":
        secrets.pop("anthropic_api_key", None)
    if body.provider == "deepseek":
        secrets.pop("deepseek_api_key", None)
    if body.provider == "gemini":
        secrets.pop("gemini_api_key", None)
    if body.provider == "ollama":
        secrets.pop("ollama_base_url", None)
    local_settings_service.write_local_settings(config.secrets_path(), secrets)
    response.headers["Cache-Control"] = "no-store"
    return SettingsOut.model_validate(_settings_payload())


def _settings_payload() -> dict[str, Any]:
    anthropic_present = bool(config.anthropic_api_key())
    ollama_present = config.ollama_base_url_configured()
    deepseek_present = bool(config.deepseek_api_key())
    gemini_present = bool(config.gemini_api_key())
    return {
        "provider": config.llm_provider(),
        "model": config.llm_model(),
        "curriculum_provider": config.curriculum_provider(),
        "curriculum_model": config.curriculum_model(),
        "credentials_present": {
            "anthropic": anthropic_present,
            "ollama": ollama_present,
            "deepseek": deepseek_present,
            "gemini": gemini_present,
        },
        "credentials": {},
        "rollout": _rollout(),
        "readiness": llm_readiness_service.settings_summary(),
    }


def _rollout() -> dict[str, Any]:
    return {"local_settings_enabled": True}


def _resolve_ollama_base_url(value: str | None) -> str:
    candidate = value.strip() if isinstance(value, str) else ""
    if not candidate:
        candidate = config.ollama_base_url()
    try:
        return normalize_ollama_base_url(candidate)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=_ollama_error_detail(
                "ollama_invalid_url",
                "ollama_invalid_url",
                "Ollama base URL must be an HTTP loopback origin.",
            ),
        ) from None


async def _discover_ollama_models_or_http_error(base_url: str) -> list[str]:
    try:
        return await discover_ollama_models(base_url)
    except OllamaDiscoveryError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=_ollama_error_detail(
                "ollama_discovery_failed",
                exc.category,
                _safe_ollama_discovery_message(exc.category),
            ),
        ) from None


def _safe_ollama_discovery_message(category: str) -> str:
    if category == "ollama_timeout":
        return "Ollama did not respond before the request timed out."
    if category == "ollama_unreachable":
        return "Ollama could not be reached."
    if category in {"ollama_no_models", "ollama_no_completion_models"}:
        return "Ollama did not report any completion-capable models."
    return "Ollama returned an invalid discovery response."


def _ollama_error_detail(
    code: str,
    failure_category: str,
    message: str,
) -> dict[str, str]:
    return {
        "code": code,
        "failure_category": failure_category,
        "message": message,
        "remediation": "Start Ollama locally, choose a loopback URL, and select an installed chat model.",
    }
