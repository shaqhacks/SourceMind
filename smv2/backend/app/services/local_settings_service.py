from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

_OWNER_ONLY_MODE = 0o600


def read_local_settings(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        data = tomllib.load(f)
    return data if isinstance(data, dict) else {}


def write_local_settings(path: Path, values: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        content = _to_toml(values)
        with tmp_path.open("w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(tmp_path, _OWNER_ONLY_MODE)
        os.replace(tmp_path, path)
        os.chmod(path, _OWNER_ONLY_MODE)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def write_local_settings_pair(
    first_path: Path,
    first_values: dict[str, Any],
    second_path: Path,
    second_values: dict[str, Any],
) -> None:
    snapshots = {
        first_path: _snapshot_path(first_path),
        second_path: _snapshot_path(second_path),
    }
    try:
        write_local_settings(first_path, first_values)
        write_local_settings(second_path, second_values)
    except Exception:
        for path, snapshot in snapshots.items():
            _restore_path(path, snapshot)
        raise


def _snapshot_path(path: Path) -> tuple[bytes | None, int | None]:
    if not path.exists():
        return None, None
    return path.read_bytes(), path.stat().st_mode & 0o777


def _restore_path(path: Path, snapshot: tuple[bytes | None, int | None]) -> None:
    content, mode = snapshot
    if content is None:
        if path.exists():
            path.unlink()
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.rollback.tmp")
    try:
        tmp_path.write_bytes(content)
        os.chmod(tmp_path, mode or _OWNER_ONLY_MODE)
        os.replace(tmp_path, path)
        os.chmod(path, mode or _OWNER_ONLY_MODE)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _to_toml(values: dict[str, Any]) -> str:
    lines: list[str] = []
    for key in sorted(values):
        value = values[key]
        if value is None:
            continue
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, int | float):
            rendered = str(value)
        elif isinstance(value, str):
            rendered = '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
        else:
            continue
        lines.append(f"{key} = {rendered}")
    return "\n".join(lines) + ("\n" if lines else "")
