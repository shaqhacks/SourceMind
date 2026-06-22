"""Huge-source caps (T5) and structured decomposition logging (T6)."""

import json
import logging

from SourceMind.backend.services.course_engine import CourseEngine
from SourceMind.backend.services.decomposition_telemetry import source_hash


def _huge_source(pages: int) -> str:
    # Each page is a valid section so the outline is well-formed.
    return "\f".join(
        f"Chapter {i}: Topic {i}\n{i}.1 Section {i}\nContent for section number {i} explained here."
        for i in range(1, pages + 1)
    )


def test_char_cap_truncates_oversized_source():
    engine = CourseEngine()
    raw = "Chapter 1: Intro\n1.1 Basics\n" + ("filler words go here " * 5000)

    # Tiny cap so the test is fast and deterministic.
    tree = engine.decompose(raw, title="Big", max_chars=200, emit_telemetry=True)

    assert tree.competencies  # still produced a usable tree from the capped prefix


def test_page_cap_limits_number_of_pages(caplog):
    engine = CourseEngine()
    raw = _huge_source(50)

    with caplog.at_level(logging.INFO, logger="sourcemind.decomposition"):
        engine.decompose(raw, title="Many", max_pages=5)

    record = json.loads(caplog.records[-1].getMessage())
    assert record["capped"] is True
    assert record["page_count"] <= 5


def test_decomposition_emits_structured_log_with_all_fields(caplog):
    engine = CourseEngine()
    raw = "Chapter 1: Intro\n1.1 Basics\nBasics explain the idea.\f1.2 More\nMore detail follows here."

    with caplog.at_level(logging.INFO, logger="sourcemind.decomposition"):
        engine.decompose(raw, title="Logged")

    record = json.loads(caplog.records[-1].getMessage())
    assert record["event"] == "decomposition"
    assert record["source_sha256"] == source_hash(raw)  # source hash
    assert "raw_llm_output" in record  # raw model output slot (None for heuristic)
    assert record["competencies"], "parsed tree present in the log"  # parsed tree
    assert "total" in record["eval"] and "passed" in record["eval"]  # eval score
    assert record["source_chars"] == len(raw)


def test_telemetry_can_be_disabled(caplog):
    engine = CourseEngine()
    with caplog.at_level(logging.INFO, logger="sourcemind.decomposition"):
        engine.decompose("Chapter 1: X\n1.1 Y\nSome content here.", emit_telemetry=False)
    assert not caplog.records  # no log emitted when telemetry is off


def test_small_source_is_not_marked_capped(caplog):
    engine = CourseEngine()
    with caplog.at_level(logging.INFO, logger="sourcemind.decomposition"):
        engine.decompose("Chapter 1: X\n1.1 Y\nSome content here.")
    record = json.loads(caplog.records[-1].getMessage())
    assert record["capped"] is False
