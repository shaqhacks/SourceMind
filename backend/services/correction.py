"""Human-in-the-loop decomposition correction — minimum slice (T7).

Lets a human edit a persisted decomposition (rename competencies, change
prerequisite edges) and re-persist it, while:

* preserving each competency's stable ``uid`` and its mastery (renames must not
  reset progress — T8), and
* rejecting any edit that introduces a prerequisite cycle, so a learner can
  never be handed an unstartable graph.

Mastery-state reconciliation (e.g. recomputing rollups when edges change) is
deliberately deferred; this slice only guarantees the safety invariants above.
"""

from __future__ import annotations

from dataclasses import dataclass

from SourceMind.backend.services.md_store import (
    Competency,
    MarkdownSubjectStore,
    SubjectDocument,
)


class CorrectionError(ValueError):
    """Base class for correction failures."""


class CompetencyNotFoundError(CorrectionError):
    pass


class PrerequisiteCycleError(CorrectionError):
    pass


class UnknownDependencyError(CorrectionError):
    pass


@dataclass(frozen=True)
class CompetencyEdit:
    """One human correction, addressed by stable uid (preferred) or display id."""

    uid: str | None = None
    id: str | None = None
    new_name: str | None = None
    new_dependencies: list[str] | None = None


def _has_dependency_cycle(competencies: list[Competency]) -> bool:
    adjacency = {c.id: list(c.dependencies) for c in competencies}
    WHITE, GREY, BLACK = 0, 1, 2
    color = {node: WHITE for node in adjacency}

    def visit(node: str) -> bool:
        color[node] = GREY
        for neighbor in adjacency.get(node, []):
            if neighbor not in color:
                continue
            if color[neighbor] == GREY:
                return True
            if color[neighbor] == WHITE and visit(neighbor):
                return True
        color[node] = BLACK
        return False

    return any(color[node] == WHITE and visit(node) for node in adjacency)


def _locate(competencies: list[Competency], edit: CompetencyEdit) -> Competency:
    for competency in competencies:
        if edit.uid is not None and competency.uid == edit.uid:
            return competency
        if edit.uid is None and edit.id is not None and competency.id == edit.id:
            return competency
    raise CompetencyNotFoundError(
        f"No competency matches edit (uid={edit.uid!r}, id={edit.id!r})."
    )


def apply_corrections(document: SubjectDocument, edits: list[CompetencyEdit]) -> SubjectDocument:
    """Return a new document with the edits applied.

    Renames preserve ``uid``, ``id``, ``level`` and ``mastery_percent`` so
    mastery is never reset. Raises a named error (and mutates nothing the caller
    persisted) if an edit targets a missing competency, references an unknown
    dependency, or would introduce a prerequisite cycle.
    """
    updated = document.model_copy(deep=True)
    valid_ids = {c.id for c in updated.competencies}

    for edit in edits:
        competency = _locate(updated.competencies, edit)
        if edit.new_name is not None:
            competency.name = edit.new_name.strip() or competency.name  # uid/mastery untouched
        if edit.new_dependencies is not None:
            cleaned = [dep.strip() for dep in edit.new_dependencies if dep.strip()]
            for dep in cleaned:
                if dep not in valid_ids:
                    raise UnknownDependencyError(
                        f"Competency {competency.id} cannot depend on unknown {dep!r}."
                    )
                if dep == competency.id:
                    raise PrerequisiteCycleError(
                        f"Competency {competency.id} cannot be its own prerequisite."
                    )
            competency.dependencies = cleaned

    if _has_dependency_cycle(updated.competencies):
        raise PrerequisiteCycleError(
            "The edited prerequisites form a cycle; rejected so the course stays learnable."
        )
    return updated


def edit_and_persist(
    store: MarkdownSubjectStore,
    subject_id: str,
    edits: list[CompetencyEdit],
) -> SubjectDocument:
    """Load, apply corrections, and persist — but never save a cyclic result."""
    document = store.load(subject_id)
    corrected = apply_corrections(document, edits)  # raises before any write on a bad edit
    store.save(corrected)
    return corrected
