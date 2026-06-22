"""Decomposition eval harness (T2).

Scores a :class:`CompetencyTree` on four *structural* rubric criteria and
compares the automated score against human-graded ground truth shipped with a
small fixture corpus. The structural rubric is the contract every future tree
producer must satisfy — the heuristic decomposer today, and any LLM-judged or
human-corrected tree later (T3, T7). Keeping it standalone means the same scorer
gates regressions no matter where the tree came from.

Rubric criteria (each scored in ``[0, 1]``):

* ``acyclic`` — the prerequisite graph is a DAG. Hard gate: a cyclic tree can
  never pass, because a learner could never start it.
* ``genuine_prerequisites`` — every prerequisite edge points at a real, distinct
  competency that appears *earlier* in the reading order. Self-loops, dangling
  ids, and forward references are not genuine prerequisites.
* ``cold_start_roots`` — there is at least one prerequisite-free entry point, and
  (for multi-node trees) not *every* node is isolated. A learner needs somewhere
  to start and a spine to climb.
* ``correct_ordering`` — every competency is presented after all of its existing
  prerequisites.

``total`` is the mean of the four. ``passed`` requires an acyclic graph, a
cold-start spine (both hard gates), and a total at or above
:data:`PASS_THRESHOLD`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from SourceMind.backend.services.course_engine import CompetencyTree, CourseEngine
    from SourceMind.backend.services.course_models import CourseCompetency


PASS_THRESHOLD = 0.75

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "decomposition"


@dataclass(frozen=True)
class RubricScore:
    acyclic: float
    genuine_prerequisites: float
    cold_start_roots: float
    correct_ordering: float
    total: float
    passed: bool
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "acyclic": self.acyclic,
            "genuine_prerequisites": self.genuine_prerequisites,
            "cold_start_roots": self.cold_start_roots,
            "correct_ordering": self.correct_ordering,
            "total": self.total,
            "passed": self.passed,
            "notes": list(self.notes),
        }


def _has_cycle(adjacency: dict[str, list[str]]) -> bool:
    """Return True if the directed graph (node -> its prerequisites) has a cycle."""
    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = {node: WHITE for node in adjacency}

    def visit(node: str) -> bool:
        color[node] = GREY
        for neighbor in adjacency.get(node, []):
            if neighbor not in color:
                continue  # dangling edge: handled by the genuineness criterion
            if color[neighbor] == GREY:
                return True
            if color[neighbor] == WHITE and visit(neighbor):
                return True
        color[node] = BLACK
        return False

    return any(color[node] == WHITE and visit(node) for node in adjacency)


def score_competency_tree(tree: CompetencyTree) -> RubricScore:
    competencies: list[CourseCompetency] = list(tree.competencies)
    notes: list[str] = []

    if not competencies:
        return RubricScore(0.0, 0.0, 0.0, 0.0, 0.0, False, ["empty tree: no competencies to score"])

    order = {comp.id: index for index, comp in enumerate(competencies)}
    adjacency = {comp.id: list(comp.prerequisite_ids) for comp in competencies}

    # --- acyclic (hard gate) ---
    acyclic = 0.0 if _has_cycle(adjacency) else 1.0
    if acyclic == 0.0:
        notes.append("prerequisite graph contains a cycle")

    # --- genuine prerequisites ---
    total_edges = 0
    genuine_edges = 0
    for comp in competencies:
        for pre in comp.prerequisite_ids:
            total_edges += 1
            if pre == comp.id:
                notes.append(f"{comp.id} lists itself as a prerequisite")
            elif pre not in order:
                notes.append(f"{comp.id} requires unknown competency {pre}")
            elif order[pre] >= order[comp.id]:
                notes.append(f"{comp.id} requires later competency {pre}")
            else:
                genuine_edges += 1
    genuine_prerequisites = 1.0 if total_edges == 0 else genuine_edges / total_edges

    # --- cold-start roots ---
    roots = [comp for comp in competencies if not comp.prerequisite_ids]
    if not roots:
        cold_start_roots = 0.0
        notes.append("no cold-start root: every competency has a prerequisite")
    elif len(competencies) > 1 and len(roots) == len(competencies):
        cold_start_roots = 0.0
        notes.append("no learning spine: every competency is an isolated root")
    else:
        cold_start_roots = 1.0

    # --- correct ordering ---
    well_ordered = 0
    for comp in competencies:
        existing = [pre for pre in comp.prerequisite_ids if pre in order]
        if all(order[pre] < order[comp.id] for pre in existing):
            well_ordered += 1
        else:
            notes.append(f"{comp.id} appears before one of its prerequisites")
    correct_ordering = well_ordered / len(competencies)

    total = (acyclic + genuine_prerequisites + cold_start_roots + correct_ordering) / 4.0
    # Acyclicity and a cold-start spine are hard gates: a learner can neither
    # start a cyclic tree nor a tree of disconnected, prerequisite-free islands.
    passed = acyclic == 1.0 and cold_start_roots == 1.0 and total >= PASS_THRESHOLD
    return RubricScore(
        acyclic=acyclic,
        genuine_prerequisites=genuine_prerequisites,
        cold_start_roots=cold_start_roots,
        correct_ordering=correct_ordering,
        total=total,
        passed=passed,
        notes=notes,
    )


@dataclass(frozen=True)
class EvalSource:
    id: str
    domain: str
    source_type: str
    messy: bool
    raw_text: str
    title: str
    ground_truth: dict[str, Any]


@dataclass(frozen=True)
class EvalResult:
    source_id: str
    domain: str
    source_type: str
    messy: bool
    harness_score: RubricScore
    ground_truth: dict[str, Any]

    @property
    def agrees_with_ground_truth(self) -> bool:
        return self.harness_score.passed == self.ground_truth.get("passed")


def load_eval_sources(fixtures_dir: Path | None = None) -> list[EvalSource]:
    """Load the curated decomposition fixture corpus from disk.

    Each entry in ``manifest.json`` names a ``.txt`` source file plus its
    domain, source type, messy flag, and human-graded ``ground_truth`` verdict.
    """
    base = fixtures_dir or FIXTURES_DIR
    manifest_path = base / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources: list[EvalSource] = []
    for entry in manifest["sources"]:
        raw_text = (base / entry["file"]).read_text(encoding="utf-8")
        sources.append(
            EvalSource(
                id=entry["id"],
                domain=entry["domain"],
                source_type=entry["source_type"],
                messy=bool(entry.get("messy", False)),
                raw_text=raw_text,
                title=entry.get("title", entry["id"]),
                ground_truth=entry["ground_truth"],
            )
        )
    return sources


def run_eval(engine: CourseEngine, sources: list[EvalSource]) -> list[EvalResult]:
    """Decompose every source, score the resulting tree, and pair it with the
    authoritative ground-truth verdict."""
    results: list[EvalResult] = []
    for source in sources:
        # Eval over fixtures must not pollute the production decomposition audit log.
        tree = engine.decompose(source.raw_text, title=source.title, emit_telemetry=False)
        score = score_competency_tree(tree)
        results.append(
            EvalResult(
                source_id=source.id,
                domain=source.domain,
                source_type=source.source_type,
                messy=source.messy,
                harness_score=score,
                ground_truth=source.ground_truth,
            )
        )
    return results


def record_eval(results: list[EvalResult], out_path: Path) -> None:
    """Persist eval scores next to their ground truth for later auditing."""
    payload = {
        "source_count": len(results),
        "passed_count": sum(1 for r in results if r.harness_score.passed),
        "ground_truth_agreement": sum(1 for r in results if r.agrees_with_ground_truth),
        "results": [
            {
                "source_id": r.source_id,
                "domain": r.domain,
                "source_type": r.source_type,
                "messy": r.messy,
                "harness_score": r.harness_score.to_dict(),
                "ground_truth": r.ground_truth,
                "agrees_with_ground_truth": r.agrees_with_ground_truth,
            }
            for r in results
        ],
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
