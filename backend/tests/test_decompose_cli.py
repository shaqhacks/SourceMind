"""Tests for the demoable decomposition CLI (T2.5)."""

import json

from SourceMind.backend.cli.decompose_cli import main

ALGEBRA = "backend/tests/fixtures/decomposition/algebra.txt"


def test_cli_prints_tree_and_rubric_for_a_source(capsys):
    exit_code = main([ALGEBRA, "--title", "Intro Algebra"])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Intro Algebra" in out
    assert "Integers" in out  # a section title from the source
    assert "COMP_1" in out  # a competency id
    assert "total" in out
    assert "PASS" in out  # the clean source passes the rubric


def test_cli_json_mode_emits_machine_readable_score(capsys):
    exit_code = main([ALGEBRA, "--title", "Intro Algebra", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["title"] == "Intro Algebra"
    assert payload["rubric"]["passed"] is True
    assert payload["rubric"]["total"] == 1.0
    assert len(payload["competencies"]) == len(
        [s for c in payload["chapters"] for s in c["sections"]]
    )


def test_cli_reads_text_flag_instead_of_file(capsys):
    exit_code = main(
        ["--text", "Chapter 1: Intro\n1.1 Basics\nBasics explain the core idea.", "--title", "Inline"]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Basics" in out


def test_cli_reports_failure_for_empty_source(capsys):
    exit_code = main(["--text", "   ", "--title", "Empty"])

    out = capsys.readouterr().out
    # No competencies can be built from empty input: the rubric must not PASS.
    assert "FAIL" in out
    assert exit_code == 1
