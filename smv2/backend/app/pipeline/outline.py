"""Outline editing operations: rename, reorder, delete, merge, split.

Framework-free — operates directly on the ORM session, taking/returning
plain dicts and ORM models rather than pydantic schemas. Executed
atomically: apply_operations() only commits once, after every operation in
the batch has succeeded, so a failure partway through leaves nothing
committed.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.identity import content_hash_for, normalize_text, section_id_for
from app.db.models import Chunk, Section
from app.pipeline.source_locators import (
    CompositeLocator,
    PdfPageLocator,
    locator_from_dict,
)


class OutlineOperationError(ValueError):
    pass


def _get_section(session: Session, course_id: str, section_id: str) -> Section:
    section = session.get(Section, section_id)
    if section is None or section.course_id != course_id:
        raise OutlineOperationError(f"section not found: {section_id}")
    return section


def _unique_section_id(
    session: Session, course_id: str, normalized_body: str, also_avoid: frozenset[str] = frozenset()
) -> str:
    """A content-addressed id for normalized_body that collides with
    neither an existing row nor another id already reserved in this same
    operation (also_avoid — needed because a not-yet-flushed sibling id
    from the same merge/split call wouldn't show up in session.get()).
    """
    occurrence = 0
    candidate = section_id_for(course_id, normalized_body, occurrence)
    while session.get(Section, candidate) is not None or candidate in also_avoid:
        occurrence += 1
        candidate = section_id_for(course_id, normalized_body, occurrence)
    return candidate


def _rederive_chunks(session: Session, section: Section) -> None:
    """Re-chunk a section whose body_md just changed shape (merge/split).
    Without retained per-page text after an edit, the whole section's text
    is attributed to its own page_start — still accurate to "which page
    range this citation falls in," which is all source_ref promises.
    """
    from app.pipeline.chunking import (
        chunk_pages,  # deferred: avoid import cost on simple ops
    )

    session.query(Chunk).filter(Chunk.section_id == section.id).delete()
    page = section.page_start if section.page_start is not None else 0
    for i, tc in enumerate(chunk_pages([(page, section.body_md)])):
        session.add(
            Chunk(
                course_id=section.course_id,
                section_id=section.id,
                chunk_index=i,
                text=tc.text,
                page=tc.page,
                source_ref=f"{section.id}:p.{tc.page + 1}",
            )
        )


def _pdf_locator_for_section(section: Section) -> PdfPageLocator:
    if section.source_format != "pdf" or section.asset_id is None:
        raise OutlineOperationError("section requires PDF source provenance")
    if section.page_start is None or section.page_end is None:
        raise OutlineOperationError("section has no page range")

    try:
        locator = locator_from_dict(section.source_locator)
    except (KeyError, TypeError, ValueError) as exc:
        raise OutlineOperationError("section has invalid PDF source locator") from exc

    if not isinstance(locator, PdfPageLocator):
        raise OutlineOperationError("section source locator is not a PDF page locator")
    if (
        locator.asset_id != section.asset_id
        or locator.page_start != section.page_start
        or locator.page_end != section.page_end
    ):
        raise OutlineOperationError("section source locator does not match its page range")
    return locator


def _merge_source_locator(sections: list[Section], page_start: int | None, page_end: int | None) -> dict[str, Any]:
    asset_ids = {section.asset_id for section in sections}
    if None in asset_ids or len(asset_ids) != 1:
        raise OutlineOperationError("merge requires sections from one source asset")

    source_formats = {section.source_format for section in sections}
    if None in source_formats or len(source_formats) != 1:
        raise OutlineOperationError("merge requires sections with one source format")

    extractor_versions = {section.extractor_version for section in sections}
    if len(extractor_versions) != 1:
        raise OutlineOperationError("merge requires sections with matching extractor provenance")

    asset_id = str(next(iter(asset_ids)))
    source_format = next(iter(source_formats))
    if source_format == "pdf":
        for section in sections:
            _pdf_locator_for_section(section)
        if page_start is None or page_end is None:
            raise OutlineOperationError("merge requires PDF sections with page ranges")
        return PdfPageLocator(asset_id=asset_id, page_start=page_start, page_end=page_end).to_dict()

    locators = []
    for section in sections:
        try:
            locator = locator_from_dict(section.source_locator)
        except (KeyError, TypeError, ValueError) as exc:
            raise OutlineOperationError("merge requires valid source locators") from exc
        if locator is None:
            raise OutlineOperationError("merge requires valid source locators")
        if locator.asset_id != section.asset_id:
            raise OutlineOperationError("section source locator does not match its source asset")
        locators.append(locator)

    try:
        return CompositeLocator.from_locators(locators).to_dict()
    except ValueError as exc:
        raise OutlineOperationError(str(exc)) from exc


def _apply_rename(session: Session, course_id: str, op: dict[str, Any]) -> None:
    section = _get_section(session, course_id, op["section_id"])
    section.title = op["title"]


def _apply_reorder(session: Session, course_id: str, op: dict[str, Any]) -> None:
    order = op["order"]
    if len(order) != len(set(order)):
        raise OutlineOperationError("reorder list contains duplicate section ids")

    current_ids = {
        s.id for s in session.query(Section).filter(Section.course_id == course_id).all()
    }
    order_set = set(order)
    if order_set != current_ids:
        missing = sorted(current_ids - order_set)
        extra = sorted(order_set - current_ids)
        raise OutlineOperationError(
            f"reorder must be an exact permutation of the course's sections "
            f"(missing={missing}, extra={extra})"
        )

    for index, section_id in enumerate(order):
        section = _get_section(session, course_id, section_id)
        section.order_index = index


def _apply_delete(session: Session, course_id: str, op: dict[str, Any]) -> None:
    section = _get_section(session, course_id, op["section_id"])
    session.delete(section)  # cascades chunks/cards; SET NULLs progress_states


def _apply_merge(session: Session, course_id: str, op: dict[str, Any]) -> str:
    section_ids = op["section_ids"]
    if len(section_ids) < 2:
        raise OutlineOperationError("merge requires at least 2 section_ids")

    sections = [_get_section(session, course_id, sid) for sid in section_ids]
    sections.sort(key=lambda s: s.order_index)

    indexes = [s.order_index for s in sections]
    if indexes != list(range(indexes[0], indexes[0] + len(indexes))):
        raise OutlineOperationError("merge requires adjacent sections (contiguous order_index)")

    merged_body = normalize_text("\n\n".join(s.body_md for s in sections))
    if not merged_body:
        raise OutlineOperationError("merge would produce an empty section")

    page_start = min((s.page_start for s in sections if s.page_start is not None), default=None)
    page_end = max((s.page_end for s in sections if s.page_end is not None), default=None)
    source_locator = _merge_source_locator(sections, page_start, page_end)
    title = " + ".join(s.title for s in sections)
    order_index = sections[0].order_index

    new_id = _unique_section_id(session, course_id, merged_body)

    new_section = Section(
        id=new_id,
        course_id=course_id,
        order_index=order_index,
        title=title,
        page_start=page_start,
        page_end=page_end,
        asset_id=sections[0].asset_id,
        source_format=sections[0].source_format,
        source_locator=source_locator,
        body_md=merged_body,
        content_hash=content_hash_for(merged_body),
        lesson_status="none",
        extractor_version=sections[0].extractor_version,
        kind=sections[0].kind,
        chapter_label=sections[0].chapter_label,
    )
    for s in sections:
        session.delete(s)
    session.add(new_section)
    session.flush()
    return new_section.id


def _apply_split(session: Session, course_id: str, op: dict[str, Any]) -> list[str]:
    section = _get_section(session, course_id, op["section_id"])
    at_page = op["at_page"]
    if section.page_start is None or section.page_end is None:
        raise OutlineOperationError("section has no page range to split")
    _pdf_locator_for_section(section)
    if not (section.page_start < at_page <= section.page_end):
        raise OutlineOperationError(f"at_page must fall within ({section.page_start}, {section.page_end}]")

    chunks = (
        session.query(Chunk)
        .filter(Chunk.section_id == section.id)
        .order_by(Chunk.chunk_index)
        .all()
    )
    if not chunks:
        raise OutlineOperationError("section has no chunks to split by")

    # at_page is the first page of the SECOND half; each chunk's own page
    # attribution places it in whichever half its page falls into — this is
    # the "chunk/page mapping" that makes the split point deterministic.
    first_chunks = [c for c in chunks if c.page < at_page]
    second_chunks = [c for c in chunks if c.page >= at_page]
    if not first_chunks or not second_chunks:
        raise OutlineOperationError("at_page does not divide this section's content")

    first_body = normalize_text("\n\n".join(c.text for c in first_chunks))
    second_body = normalize_text("\n\n".join(c.text for c in second_chunks))
    if not first_body or not second_body:
        raise OutlineOperationError("split would produce an empty section")

    first_id = _unique_section_id(session, course_id, first_body)
    second_id = _unique_section_id(session, course_id, second_body, also_avoid=frozenset({first_id}))

    # Make room: every later section's order_index shifts up by one.
    later_sections = (
        session.query(Section)
        .filter(Section.course_id == course_id, Section.order_index > section.order_index)
        .all()
    )
    for later in later_sections:
        later.order_index += 1

    first_section = Section(
        id=first_id,
        course_id=course_id,
        order_index=section.order_index,
        title=f"{section.title} (1)",
        asset_id=section.asset_id,
        page_start=section.page_start,
        page_end=at_page - 1,
        source_format=section.source_format,
        source_locator=PdfPageLocator(
            asset_id=str(section.asset_id),
            page_start=section.page_start,
            page_end=at_page - 1,
        ).to_dict(),
        body_md=first_body,
        content_hash=content_hash_for(first_body),
        lesson_status="none",
        extractor_version=section.extractor_version,
        kind=section.kind,
        chapter_label=section.chapter_label,
    )
    second_section = Section(
        id=second_id,
        course_id=course_id,
        order_index=section.order_index + 1,
        title=f"{section.title} (2)",
        asset_id=section.asset_id,
        page_start=at_page,
        page_end=section.page_end,
        source_format=section.source_format,
        source_locator=PdfPageLocator(
            asset_id=str(section.asset_id),
            page_start=at_page,
            page_end=section.page_end,
        ).to_dict(),
        body_md=second_body,
        content_hash=content_hash_for(second_body),
        lesson_status="none",
        extractor_version=section.extractor_version,
        kind=section.kind,
        chapter_label=section.chapter_label,
    )

    session.delete(section)
    session.add_all([first_section, second_section])
    session.flush()
    return [first_section.id, second_section.id]


_OPERATION_HANDLERS = {
    "rename": _apply_rename,
    "reorder": _apply_reorder,
    "delete": _apply_delete,
    "merge": _apply_merge,
    "split": _apply_split,
}


def apply_operations(session: Session, course_id: str, operations: list[dict[str, Any]]) -> list[Section]:
    """Execute every operation in order. Raises OutlineOperationError (and
    commits nothing) on the first invalid operation — callers must
    session.rollback() on failure.
    """
    affected_section_ids: set[str] = set()

    for op in operations:
        op_type = op.get("type")
        handler = _OPERATION_HANDLERS.get(op_type)
        if handler is None:
            raise OutlineOperationError(f"unknown outline operation: {op_type}")
        result = handler(session, course_id, op)
        if isinstance(result, str):
            affected_section_ids.add(result)
        elif isinstance(result, list):
            affected_section_ids.update(result)

    session.flush()

    # Only merge/split changed body_md shape; rename/reorder/delete don't
    # touch chunk content, so only re-derive chunks for what merge/split
    # actually returned.
    for section_id in affected_section_ids:
        section = session.get(Section, section_id)
        if section is not None:
            _rederive_chunks(session, section)

    session.commit()
    return (
        session.query(Section)
        .filter(Section.course_id == course_id)
        .order_by(Section.order_index)
        .all()
    )
