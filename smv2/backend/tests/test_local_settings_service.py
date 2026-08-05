from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_local_settings_writes_secrets_atomically_with_owner_only_mode(tmp_path):
    from app.services.local_settings_service import read_local_settings, write_local_settings

    settings_path = tmp_path / "settings.toml"

    write_local_settings(
        settings_path,
        {
            "provider": "anthropic",
            "model": "claude-sonnet-5",
            "anthropic_api_key": "sk-ant-test-secret",
        },
    )

    assert settings_path.is_file()
    assert oct(settings_path.stat().st_mode & 0o777) == "0o600"
    assert read_local_settings(settings_path)["anthropic_api_key"] == "sk-ant-test-secret"


def test_local_settings_failed_replace_leaves_existing_file_intact(tmp_path, monkeypatch):
    from app.services import local_settings_service

    settings_path = tmp_path / "settings.toml"
    settings_path.write_text('provider = "anthropic"\n', encoding="utf-8")
    os.chmod(settings_path, 0o600)

    def fail_replace(src: str | Path, dst: str | Path):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(local_settings_service.os, "replace", fail_replace)

    with pytest.raises(OSError):
        local_settings_service.write_local_settings(
            settings_path,
            {"provider": "ollama", "ollama_base_url": "http://127.0.0.1:11434"},
        )

    assert settings_path.read_text(encoding="utf-8") == 'provider = "anthropic"\n'
    assert list(tmp_path.glob("*.tmp")) == []
