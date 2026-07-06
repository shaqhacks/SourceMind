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


def parse_prompt_version(version: str) -> int:
    """Parses a 'vN' prompt-version string into its integer N, so version
    comparisons are numeric ('v10' > 'v9') rather than lexicographic — as
    plain strings, 'v10' < 'v9' (the '1' in "v10" sorts before the '9' in
    "v9"), which silently broke lesson staleness at v10. Use this anywhere
    two 'vN' strings need comparing, not just here.
    """
    return int(version.lstrip("v"))


def load_prompt(name: str) -> tuple[str, str]:
    """Loads the latest version of backend/prompts/vN/{name}.md.

    Returns (text, version) where version is the directory name (e.g.
    'v1') — always the highest vN present, so adding a new prompts/v2/
    directory picks it up automatically without a code change.
    """
    prompts_root = _BACKEND_ROOT / "prompts"
    versions = sorted(
        (d for d in prompts_root.iterdir() if d.is_dir() and d.name.startswith("v")),
        key=lambda d: parse_prompt_version(d.name),
    )
    if not versions:
        raise FileNotFoundError(f"no prompt versions found under {prompts_root}")

    latest = versions[-1]
    prompt_path = latest / f"{name}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"prompt not found: {prompt_path}")

    return prompt_path.read_text(), latest.name
