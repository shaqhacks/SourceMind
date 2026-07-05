"""Prompts live as files under backend/prompts/vN/, never as string
literals in code (see the >300-char-literal architecture test) — this
keeps prompt changes reviewable as plain diffs and makes prompt_version
tracking trivial (the version is just the directory name).
"""

from __future__ import annotations

from pathlib import Path

# app/llm/prompts.py -> app/llm -> app -> backend (NOT app.config.repo_root(),
# which points at the outer smv2 monorepo root — prompts/ lives directly
# under backend/, one level closer than that).
_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


def _version_key(version_dir_name: str) -> int:
    return int(version_dir_name.lstrip("v"))


def load_prompt(name: str) -> tuple[str, str]:
    """Loads the latest version of backend/prompts/vN/{name}.md.

    Returns (text, version) where version is the directory name (e.g.
    'v1') — always the highest vN present, so adding a new prompts/v2/
    directory picks it up automatically without a code change.
    """
    prompts_root = _BACKEND_ROOT / "prompts"
    versions = sorted(
        (d for d in prompts_root.iterdir() if d.is_dir() and d.name.startswith("v")),
        key=lambda d: _version_key(d.name),
    )
    if not versions:
        raise FileNotFoundError(f"no prompt versions found under {prompts_root}")

    latest = versions[-1]
    prompt_path = latest / f"{name}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"prompt not found: {prompt_path}")

    return prompt_path.read_text(), latest.name
