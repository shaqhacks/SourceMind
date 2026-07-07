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
    """Loads backend/prompts/vN/{name}.md from the HIGHEST vN directory
    that actually CONTAINS that file — per-file resolution, not "the one
    highest vN overall" (ADR-022). This lets a new prompts/v3/ directory
    hold just ONE changed prompt (e.g. only chat.md) without silently
    bumping every other prompt's effective version too: lesson/cards/quiz
    keep resolving to their own highest version that actually has their
    file (v2, unchanged) even once v3 exists, since their content hasn't
    changed and a wholesale version bump would flip lesson_stale for
    every section for no reason.

    Returns (text, version) where version is the directory name (e.g.
    'v2') of the highest vN directory containing {name}.md specifically.
    """
    prompts_root = _BACKEND_ROOT / "prompts"
    versions = sorted(
        (d for d in prompts_root.iterdir() if d.is_dir() and d.name.startswith("v")),
        key=lambda d: parse_prompt_version(d.name),
        reverse=True,
    )
    if not versions:
        raise FileNotFoundError(f"no prompt versions found under {prompts_root}")

    for version_dir in versions:
        prompt_path = version_dir / f"{name}.md"
        if prompt_path.exists():
            return prompt_path.read_text(), version_dir.name

    raise FileNotFoundError(f"{name}.md not found in any version directory under {prompts_root}")
