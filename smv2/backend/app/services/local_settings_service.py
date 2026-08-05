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
