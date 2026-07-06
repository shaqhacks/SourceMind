from __future__ import annotations

import app.config as config


def test_db_url_is_read_lazily(monkeypatch):
    monkeypatch.setenv("SMV2_DB_URL", "sqlite:////tmp/lazy-test-1.db")
    assert config.db_url() == "sqlite:////tmp/lazy-test-1.db"

    monkeypatch.setenv("SMV2_DB_URL", "sqlite:////tmp/lazy-test-2.db")
    assert config.db_url() == "sqlite:////tmp/lazy-test-2.db"


def test_max_upload_bytes_is_read_lazily(monkeypatch):
    assert config.max_upload_bytes() == 200 * 1024 * 1024

    monkeypatch.setenv("SMV2_MAX_UPLOAD_BYTES", "12345")
    assert config.max_upload_bytes() == 12345

    monkeypatch.setenv("SMV2_MAX_UPLOAD_BYTES", "not-a-number")
    assert config.max_upload_bytes() == 200 * 1024 * 1024


def test_pages_per_window_is_read_lazily(monkeypatch):
    assert config.pages_per_window() == 12

    monkeypatch.setenv("SMV2_PAGES_PER_WINDOW", "7")
    assert config.pages_per_window() == 7

    monkeypatch.setenv("SMV2_PAGES_PER_WINDOW", "not-a-number")
    assert config.pages_per_window() == 12


def test_skip_front_matter_is_read_lazily(monkeypatch):
    assert config.skip_front_matter() is True

    monkeypatch.setenv("SMV2_SKIP_FRONT_MATTER", "0")
    assert config.skip_front_matter() is False

    monkeypatch.setenv("SMV2_SKIP_FRONT_MATTER", "1")
    assert config.skip_front_matter() is True


def _write_secrets(tmp_path, monkeypatch, contents: str) -> None:
    monkeypatch.setenv("SMV2_DATA_DIR", str(tmp_path))
    (tmp_path / "secrets.toml").write_text(contents)


def test_anthropic_api_key_none_when_neither_env_nor_file_set(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("SMV2_DATA_DIR", str(tmp_path))
    assert config.anthropic_api_key() is None


def test_anthropic_api_key_falls_back_to_secrets_file_when_env_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _write_secrets(tmp_path, monkeypatch, 'anthropic_api_key = "sk-from-file"\n')
    assert config.anthropic_api_key() == "sk-from-file"


def test_anthropic_api_key_env_takes_precedence_over_secrets_file(tmp_path, monkeypatch):
    _write_secrets(tmp_path, monkeypatch, 'anthropic_api_key = "sk-from-file"\n')
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    assert config.anthropic_api_key() == "sk-from-env"


def test_anthropic_api_key_malformed_toml_returns_none_not_crash(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _write_secrets(tmp_path, monkeypatch, "this is not valid toml {{{\n")
    assert config.anthropic_api_key() is None


def test_anthropic_api_key_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("SMV2_DATA_DIR", str(tmp_path))  # directory exists, no secrets.toml in it
    assert config.anthropic_api_key() is None


def test_ollama_base_url_falls_back_to_secrets_file_when_env_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("SMV2_OLLAMA_BASE_URL", raising=False)
    _write_secrets(tmp_path, monkeypatch, 'ollama_base_url = "http://file-configured:11434"\n')
    assert config.ollama_base_url() == "http://file-configured:11434"


def test_ollama_base_url_env_takes_precedence_over_secrets_file(tmp_path, monkeypatch):
    _write_secrets(tmp_path, monkeypatch, 'ollama_base_url = "http://file-configured:11434"\n')
    monkeypatch.setenv("SMV2_OLLAMA_BASE_URL", "http://env-configured:11434")
    assert config.ollama_base_url() == "http://env-configured:11434"


def test_ollama_base_url_default_when_neither_set(tmp_path, monkeypatch):
    monkeypatch.delenv("SMV2_OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("SMV2_DATA_DIR", str(tmp_path))
    assert config.ollama_base_url() == "http://localhost:11434"
