"""Demoable decomposition CLI (T2.5).

Ingest a source (file, ``--text``, or stdin), run :meth:`CourseEngine.decompose`
plus the eval rubric scorer, and print the competency tree and its rubric score.
This is the forcing function that makes the decomposition + eval moat work
produce a visible, runnable result:

    python -m SourceMind.backend.cli.decompose_cli path/to/source.txt
    python -m SourceMind.backend.cli.decompose_cli --text "Chapter 1: ..." --json

Exit code is 0 when the tree passes the rubric, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from SourceMind.backend.services.course_engine import (
    CompetencyTree,
    CourseEngine,
    EmptyDecompositionError,
    MalformedDecompositionError,
)
from SourceMind.backend.services.decomposition_eval import RubricScore, score_competency_tree


def _read_source(args: argparse.Namespace) -> str:
    if args.text is not None:
        return args.text
    if args.source in (None, "-"):
        return sys.stdin.read()
    return Path(args.source).read_text(encoding="utf-8")


def _tree_to_payload(tree: CompetencyTree) -> dict:
    return {
        "chapters": [
            {
                "id": chapter.id,
                "number": chapter.number,
                "title": chapter.title,
                "sections": [
                    {
                        "id": section.id,
                        "number": section.number,
                        "title": section.title,
                        "competency_ids": list(section.competency_ids),
                    }
                    for section in chapter.sections
                ],
            }
            for chapter in tree.chapters
        ],
        "competencies": [
            {
                "id": comp.id,
                "title": comp.title,
                "level": comp.level,
                "prerequisite_ids": list(comp.prerequisite_ids),
            }
            for comp in tree.competencies
        ],
    }


def _print_human(title: str, tree: CompetencyTree, score: RubricScore) -> None:
    print(f"Source: {title}")
    print("\nCompetency tree:")
    if not tree.chapters:
        print("  (no chapters detected)")
    comp_by_id = {comp.id: comp for comp in tree.competencies}
    for chapter in tree.chapters:
        print(f"  CH {chapter.number}: {chapter.title}")
        for section in chapter.sections:
            comp_ids = ", ".join(section.competency_ids)
            prereqs = sorted(
                {
                    pre
                    for cid in section.competency_ids
                    if cid in comp_by_id
                    for pre in comp_by_id[cid].prerequisite_ids
                }
            )
            suffix = f" (requires {', '.join(prereqs)})" if prereqs else ""
            print(f"    {section.number} {section.title} -> {comp_ids}{suffix}")

    print("\nRubric score:")
    for name in ("acyclic", "genuine_prerequisites", "cold_start_roots", "correct_ordering", "total"):
        print(f"  {name:<22} {getattr(score, name):.2f}")
    for note in score.notes:
        print(f"  - {note}")
    print(f"\n{'PASS' if score.passed else 'FAIL'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="decompose_cli",
        description="Decompose a source into a competency tree and score it with the eval rubric.",
    )
    parser.add_argument("source", nargs="?", help="path to a source text file, or '-' for stdin")
    parser.add_argument("--text", help="inline source text instead of a file")
    parser.add_argument("--title", default="Untitled Source", help="course title for the source")
    parser.add_argument("--model", default="llama3.1", help="LLM model name (unused by decompose)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)

    raw_text = _read_source(args)
    engine = CourseEngine(model=args.model)
    try:
        tree = engine.decompose(raw_text, title=args.title)
    except (EmptyDecompositionError, MalformedDecompositionError) as exc:
        if args.json:
            print(json.dumps({"title": args.title, "error": str(exc), "passed": False}, indent=2))
        else:
            print(f"Source: {args.title}\n\n{exc}\n\nFAIL")
        return 1
    score = score_competency_tree(tree)

    if args.json:
        payload = {"title": args.title, **_tree_to_payload(tree), "rubric": score.to_dict()}
        print(json.dumps(payload, indent=2))
    else:
        _print_human(args.title, tree, score)

    return 0 if score.passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
