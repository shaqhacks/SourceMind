from __future__ import annotations

from app.llm.prompts import load_prompt, parse_prompt_version


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


def test_load_prompt_picks_v2_now_that_it_exists():
    """v2 adds the LaTeX-math instruction to all four prompts -- confirms
    load_prompt's "always the highest vN present" contract actually picks
    it up now that prompts/v2/ exists alongside v1.
    """
    for name in ["lesson", "cards", "quiz", "chat"]:
        text, version = load_prompt(name)
        assert version == "v2", name
        assert "LaTeX" in text, name
        assert "$" in text, name
