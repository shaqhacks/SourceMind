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


def test_secret_settings_use_secrets_toml_contract(tmp_path):
    from app.services.local_settings_service import read_local_settings, write_local_settings

    secrets_path = tmp_path / "secrets.toml"

    write_local_settings(secrets_path, {"anthropic_api_key": "sk-ant-test-secret"})

    assert secrets_path.name == "secrets.toml"
    assert oct(secrets_path.stat().st_mode & 0o777) == "0o600"
    assert read_local_settings(secrets_path) == {"anthropic_api_key": "sk-ant-test-secret"}


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


def test_two_file_settings_write_rolls_back_both_files_byte_for_byte_on_second_write_failure(
    tmp_path, monkeypatch
):
    from app.services import local_settings_service

    local_path = tmp_path / "local_settings.toml"
    secrets_path = tmp_path / "secrets.toml"
    local_path.write_bytes(b'provider = "anthropic"\nmodel = "claude-sonnet-5"\n')
    secrets_path.write_bytes(b'anthropic_api_key = "sk-ant-original"\n')
    os.chmod(local_path, 0o600)
    os.chmod(secrets_path, 0o600)
    before_local = local_path.read_bytes()
    before_secrets = secrets_path.read_bytes()

    original_write = local_settings_service.write_local_settings

    def fail_secrets_write(path: Path, values: dict):
        if path == secrets_path:
            raise OSError("simulated secrets write failure")
        original_write(path, values)

    monkeypatch.setattr(local_settings_service, "write_local_settings", fail_secrets_write)

    with pytest.raises(OSError):
        local_settings_service.write_local_settings_pair(
            local_path,
            {"provider": "ollama", "model": "llama3.2"},
            secrets_path,
            {"anthropic_api_key": "sk-ant-new", "ollama_base_url": "http://127.0.0.1:11434"},
        )

    assert local_path.read_bytes() == before_local
    assert secrets_path.read_bytes() == before_secrets


def test_two_file_settings_write_rolls_back_both_files_byte_for_byte_on_first_write_failure(
    tmp_path, monkeypatch
):
    from app.services import local_settings_service

    local_path = tmp_path / "local_settings.toml"
    secrets_path = tmp_path / "secrets.toml"
    local_path.write_bytes(b'provider = "anthropic"\nmodel = "claude-sonnet-5"\n')
    secrets_path.write_bytes(b'anthropic_api_key = "sk-ant-original"\n')
    os.chmod(local_path, 0o600)
    os.chmod(secrets_path, 0o600)
    before_local = local_path.read_bytes()
    before_secrets = secrets_path.read_bytes()

    original_write = local_settings_service.write_local_settings

    def fail_local_write(path: Path, values: dict):
        if path == local_path:
            raise OSError("simulated local settings write failure")
        original_write(path, values)

    monkeypatch.setattr(local_settings_service, "write_local_settings", fail_local_write)

    with pytest.raises(OSError):
        local_settings_service.write_local_settings_pair(
            local_path,
            {"provider": "ollama", "model": "llama3.2"},
            secrets_path,
            {"anthropic_api_key": "sk-ant-new"},
        )

    assert local_path.read_bytes() == before_local
    assert secrets_path.read_bytes() == before_secrets
