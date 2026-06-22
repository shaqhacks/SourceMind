"""Stable competency identity (T8) + human correction with cycle rejection (T7)."""

from pathlib import Path

import pytest

from SourceMind.backend.services.correction import (
    CompetencyEdit,
    CompetencyNotFoundError,
    PrerequisiteCycleError,
    UnknownDependencyError,
    apply_corrections,
    edit_and_persist,
)
from SourceMind.backend.services.md_store import (
    Competency,
    MarkdownSubjectStore,
    SRSData,
    SubjectDocument,
)


def _doc() -> SubjectDocument:
    return SubjectDocument(
        subject_id="algebra",
        competencies=[
            Competency(id="C1", name="Integers", level=1, dependencies=[], mastery_percent=70, uid="uid-1"),
            Competency(id="C2", name="Fractions", level=1, dependencies=["C1"], mastery_percent=40, uid="uid-2"),
        ],
        srs_data={"C1": SRSData(interval=5, last_score=88)},
    )


# --- T8: stable uid survives persistence and rename ---

def test_competency_uid_round_trips_through_markdown(tmp_path: Path):
    store = MarkdownSubjectStore(tmp_path)
    store.save(_doc())
    loaded = store.load("algebra")
    assert [c.uid for c in loaded.competencies] == ["uid-1", "uid-2"]


def test_competency_name_with_pipe_round_trips(tmp_path: Path):
    # Source-derived names can contain '|'; it must not corrupt the table columns.
    store = MarkdownSubjectStore(tmp_path)
    store.save(
        SubjectDocument(
            subject_id="piped",
            competencies=[
                Competency(id="C1", name="A | B notation", level=1, dependencies=[], mastery_percent=33, uid="uid-x")
            ],
        )
    )
    loaded = MarkdownSubjectStore(tmp_path).load("piped")
    assert loaded.competencies[0].name == "A | B notation"
    assert loaded.competencies[0].uid == "uid-x"
    assert loaded.competencies[0].mastery_percent == 33


def test_legacy_five_column_table_gets_a_backfilled_uid(tmp_path: Path):
    (tmp_path / "legacy.md").write_text(
        "---\ncurrent_level: 1\ntotal_mastery: 0\n---\n\n"
        "## COMPETENCY_MAP:\n"
        "| ID | Name | Level | Dependencies | Mastery % |\n"
        "| --- | --- | ---: | --- | ---: |\n"
        "| C1 | Integers | 1 | - | 50% |\n",
        encoding="utf-8",
    )
    loaded = MarkdownSubjectStore(tmp_path).load("legacy")
    assert loaded.competencies[0].uid  # backfilled, non-empty
    assert loaded.competencies[0].mastery_percent == 50


def test_rename_preserves_uid_and_mastery(tmp_path: Path):
    store = MarkdownSubjectStore(tmp_path)
    store.save(_doc())

    corrected = edit_and_persist(
        store, "algebra", [CompetencyEdit(uid="uid-1", new_name="Whole Numbers")]
    )

    c1 = next(c for c in corrected.competencies if c.uid == "uid-1")
    assert c1.name == "Whole Numbers"  # renamed
    assert c1.id == "C1"  # structural id unchanged
    assert c1.mastery_percent == 70  # mastery NOT reset
    # Persisted state agrees.
    reloaded = store.load("algebra")
    c1r = next(c for c in reloaded.competencies if c.uid == "uid-1")
    assert c1r.name == "Whole Numbers" and c1r.mastery_percent == 70
    assert reloaded.srs_data["C1"].last_score == 88  # SRS history intact


# --- T7: human correction with prerequisite-cycle rejection ---

def test_valid_dependency_edit_is_applied():
    doc = _doc()
    # Clearing C2's prerequisite is a valid, acyclic edit.
    corrected = apply_corrections(doc, [CompetencyEdit(id="C2", new_dependencies=[])])
    # original doc untouched; correction returns a new document
    assert doc.competencies[1].dependencies == ["C1"]
    assert corrected.competencies[1].dependencies == []


def test_self_dependency_is_rejected():
    with pytest.raises(PrerequisiteCycleError):
        apply_corrections(_doc(), [CompetencyEdit(id="C1", new_dependencies=["C1"])])


def test_cycle_inducing_edit_is_rejected():
    # C2 already depends on C1; making C1 depend on C2 closes the loop.
    with pytest.raises(PrerequisiteCycleError):
        apply_corrections(_doc(), [CompetencyEdit(id="C1", new_dependencies=["C2"])])


def test_unknown_dependency_is_rejected():
    with pytest.raises(UnknownDependencyError):
        apply_corrections(_doc(), [CompetencyEdit(id="C1", new_dependencies=["C999"])])


def test_missing_target_is_rejected():
    with pytest.raises(CompetencyNotFoundError):
        apply_corrections(_doc(), [CompetencyEdit(uid="nope", new_name="x")])


def test_cyclic_edit_is_not_persisted(tmp_path: Path):
    store = MarkdownSubjectStore(tmp_path)
    store.save(_doc())
    with pytest.raises(PrerequisiteCycleError):
        edit_and_persist(store, "algebra", [CompetencyEdit(id="C1", new_dependencies=["C2"])])
    # File on disk is unchanged: C1 still has no dependencies.
    reloaded = store.load("algebra")
    assert next(c for c in reloaded.competencies if c.id == "C1").dependencies == []
