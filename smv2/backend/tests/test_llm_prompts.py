from __future__ import annotations

from app.llm.prompts import parse_prompt_version


def test_parse_prompt_version_extracts_the_integer():
    assert parse_prompt_version("v1") == 1
    assert parse_prompt_version("v9") == 9
    assert parse_prompt_version("v10") == 10
    assert parse_prompt_version("v123") == 123


def test_parse_prompt_version_v9_less_than_v10_numerically():
    """The whole point: as plain strings, 'v9' > 'v10' (lexicographic
    comparison sees '9' > '1' at the second character), which is exactly
    backwards from the numeric truth — a v9 lesson would silently NOT be
    flagged stale once the prompt reached v10. Comparison must be numeric.
    """
    assert "v9" > "v10"  # sanity: confirms the string comparison IS the trap
    assert parse_prompt_version("v9") < parse_prompt_version("v10")
    assert not parse_prompt_version("v10") < parse_prompt_version("v9")
