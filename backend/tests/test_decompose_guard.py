"""Empty/malformed/refusal guards for decomposition (T1).

decompose() must never return an empty or partial tree: empty or unstructurable
input raises a named error whose user-facing message tells the learner we
"couldn't structure this source". LLM-structured output that is empty, malformed
JSON, or a refusal is rejected the same way, retried once with a stricter prompt,
and never persisted if it stays bad.
"""

import pytest

from SourceMind.backend.services.course_engine import (
    CourseEngine,
    EmptyDecompositionError,
    MalformedDecompositionError,
    parse_competency_json,
    structure_with_retry,
)


def test_decompose_rejects_empty_text_with_user_message():
    engine = CourseEngine()
    with pytest.raises(EmptyDecompositionError) as exc:
        engine.decompose("   \n\t  ", title="Empty")
    assert "couldn't structure this source" in str(exc.value).lower()


def test_decompose_rejects_image_only_pdf_text():
    # An image-only PDF extracts to no selectable text -> empty raw_text.
    engine = CourseEngine()
    with pytest.raises(EmptyDecompositionError):
        engine.decompose("", title="Scanned Slides")


def test_decompose_never_returns_empty_tree_for_valid_text():
    engine = CourseEngine()
    tree = engine.decompose("Chapter 1: Intro\n1.1 Basics\nBasics explain the core idea.", title="Ok")
    assert tree.competencies, "valid input must yield a non-empty tree"


def test_parse_competency_json_rejects_malformed_json():
    with pytest.raises(MalformedDecompositionError) as exc:
        parse_competency_json("{ this is not : valid json ")
    assert "malformed" in str(exc.value).lower()


def test_parse_competency_json_rejects_refusal():
    with pytest.raises(MalformedDecompositionError) as exc:
        parse_competency_json("I'm sorry, but I can't help with structuring that content.")
    assert "refus" in str(exc.value).lower()


def test_parse_competency_json_rejects_empty_competencies():
    with pytest.raises(EmptyDecompositionError):
        parse_competency_json('{"competencies": []}')


def test_parse_competency_json_accepts_well_formed_output():
    payload = parse_competency_json('{"competencies": [{"title": "Integers"}]}')
    assert payload["competencies"][0]["title"] == "Integers"


def test_valid_json_with_refusal_phrase_in_value_is_not_a_refusal():
    # A refusal marker inside a legitimate JSON value must NOT trip the guard.
    payload = parse_competency_json('{"competencies": [{"title": "When I cannot apply the rule"}]}')
    assert payload["competencies"][0]["title"] == "When I cannot apply the rule"


def test_structure_with_retry_retries_once_then_succeeds():
    calls = []

    def structurer(prompt: str) -> str:
        calls.append(prompt)
        if len(calls) == 1:
            return "I cannot do that."  # first attempt: refusal
        return '{"competencies": [{"title": "Integers"}]}'  # stricter retry: valid

    payload = structure_with_retry(structurer, prompt="base", stricter_prompt="stricter")

    assert payload["competencies"][0]["title"] == "Integers"
    assert calls == ["base", "stricter"]  # exactly one retry, with the stricter prompt


def test_structure_with_retry_raises_after_second_failure_and_never_persists():
    attempts = []

    def structurer(prompt: str) -> str:
        attempts.append(prompt)
        return "{ broken json"

    with pytest.raises(MalformedDecompositionError):
        structure_with_retry(structurer, prompt="base", stricter_prompt="stricter")
    assert len(attempts) == 2  # tried once, retried once, then gave up — no third attempt
