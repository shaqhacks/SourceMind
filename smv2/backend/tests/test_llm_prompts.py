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
    load_prompt's per-file "highest vN that HAS this file" contract picks
    it up now that prompts/v2/ exists alongside v1. chat resolves to v3
    (ADR-022's learning-companion persona), the other three still resolve
    to v2 -- see test_load_prompt_resolves_per_file_not_globally below for
    that distinction asserted directly.
    """
    for name in ["lesson", "cards", "quiz"]:
        text, version = load_prompt(name)
        assert version == "v2", name
        assert "LaTeX" in text, name
        assert "$" in text, name

    chat_text, chat_version = load_prompt("chat")
    assert chat_version == "v3"
    assert "LaTeX" in chat_text
    assert "$" in chat_text


def test_load_prompt_resolves_per_file_not_globally():
    """ADR-022: prompts/v3/ may hold selected changed prompts -- load_prompt must resolve
    each file to the highest version directory that actually CONTAINS it,
    not "the single highest vN overall" (which would wrongly report v3
    for lesson/cards/quiz too, even though neither file exists there and
    their content hasn't changed since v2).
    """
    import os

    from app.llm.prompts import _BACKEND_ROOT

    v3_dir = _BACKEND_ROOT / "prompts" / "v3"
    assert os.path.isdir(v3_dir)
    v3_files = {p.name for p in v3_dir.iterdir()}
    assert v3_files == {"chat.md", "practice_assessment.md"}

    assert load_prompt("chat")[1] == "v3"
    assert load_prompt("practice_assessment")[1] == "v3"
    assert load_prompt("lesson")[1] == "v2"
    assert load_prompt("cards")[1] == "v2"
    assert load_prompt("quiz")[1] == "v2"
