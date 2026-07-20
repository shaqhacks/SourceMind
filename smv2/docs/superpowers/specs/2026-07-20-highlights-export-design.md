# Design — highlights/notes in the course export (2026-07-20)

## Goal

Include a user's highlights and notes in the course-export zip so their own
annotations are never hostage to the app — the same data-ownership principle
that already drives `outline.md`, per-section `body_md`, ready lessons, and
the original PDFs into the archive.

Chosen intent: **lossless / machine round-trip**. Emit a complete, versioned
`highlights.json` carrying every field (including the text-quote anchor), as a
stable contract a future re-import path can read. This does NOT build any
import machinery now — re-import and re-ingest-survival remain separately
deferred.

## Current state (what already exists)

`app/services/export_service.build_export_zip(course_id)` streams a zip
containing:

- `outline.md` — table of contents linking to each section file
- `NN-slug.md` per section — immutable `body_md` source text
- `lessons/NN-slug.lesson.md` — generated lesson, only when
  `lesson_status == "ready"` (conditional by design)
- `manifest.json` — course meta + per-section `{id, title, order_index,
  content_hash, extractor_version, lesson metadata}`
- `assets/<name>` — original PDFs

`app/services/highlights_service.list_highlights(course_id)` returns a list of
**already-converted dicts** — `page` run through `to_display_page` (1-based),
ordered by `Section.order_index, Highlight.created_at`, one dict per highlight
with the full field set (`id, course_id, section_id, exact, prefix, suffix,
occurrence, page, color, surface, note_md, created_at, updated_at`).

`Highlight` (`app/db/models.py`) stores `page` **0-based**; the API surface is
**1-based**. The single conversion lives in `highlights_service`
(`to_display_page`). Highlights are wiped on re-ingest (ADR-024, REPLACED
bucket).

## Design

### Where

Add exactly one file, `highlights.json`, at the zip root (beside
`manifest.json`) inside `build_export_zip`. Source it from
`highlights_service.list_highlights(course_id)`.

**Reuse the service, do not re-query the model.** Re-querying `Highlight`
inside the export's own session would read the raw 0-based `page` and silently
desync from the 1-based API — reintroducing the exact bug the single-conversion
rule prevents. Calling `list_highlights` keeps that rule intact and reuses the
field set the API already exposes. The extra short-lived read session it opens
is harmless (independent reads, SQLite).

### Schema

```json
{
  "schema_version": 1,
  "course_id": "<course id>",
  "highlights": [
    {
      "id": "<highlight id>",
      "course_id": "<course id>",
      "section_id": "<section id>",
      "exact": "<selected text>",
      "prefix": "<anchor prefix, may be empty>",
      "suffix": "<anchor suffix, may be empty>",
      "occurrence": 0,
      "page": 12,
      "color": "yellow",
      "surface": "pdf",
      "note_md": "<note markdown or null>",
      "created_at": "<iso8601>",
      "updated_at": "<iso8601>"
    }
  ]
}
```

- **Flat array, not grouped by section.** `section_id` is the join key and
  `manifest.json` already maps `section_id → file`; nesting by section would
  duplicate structure a machine consumer does not need.
- `page` is **1-based**, `null` for `surface == "source"` highlights (matches
  the API).
- `note_md` is `null` when there is no note.
- `schema_version` is the contract for a future importer. It is `1`.
- Datetimes serialize as strings via the same `json.dumps(..., default=str)`
  the manifest already uses.

### Always emitted

`highlights.json` is written on **every** export, with `"highlights": []` when
the course has none. A round-trip consumer must not have to special-case "file
absent = zero highlights." (This differs from the per-section lesson files,
which are legitimately conditional on readiness.)

### Ordering

Preserve `list_highlights`'s order: `Section.order_index, then created_at`.
Stable ordering keeps export diffs meaningful and gives an importer a
deterministic sequence.

## Explicitly out of scope (YAGNI)

- No import / re-anchor code. Re-import and re-ingest-survival stay deferred.
- No human-readable `notes.md`. Intent is machine round-trip only.
- No frontend change. Adding a file to the streamed zip is invisible to the
  export client; the existing download flow is unchanged.
- No `manifest.json` change. Highlights are a distinct concern in their own
  file; the manifest stays a stable structural record.

## Testing

Extend `backend/tests/test_export.py`:

1. **Round-trip a highlight.** Ingest a course, create a highlight via
   `POST /api/courses/{course_id}/highlights` (with a real `section_id`,
   `surface`, `page`, `color`, `note_md`), export, and assert
   `highlights.json` is present, parses as JSON, has `schema_version == 1` and
   `course_id`, and that the highlight round-trips field-for-field — including
   **1-based `page`** and `surface`.
2. **Empty case.** A course with no highlights still yields `highlights.json`
   with `"highlights": []` (not an absent file).

Existing export tests must stay green (the new file is additive). Full backend
pytest + `./build.sh` gate from `smv2/` before done.

## ADR

No new ADR. This extends the existing export whose data-ownership rationale is
already recorded in the `export_service` module docstring and ADR-024. The
`schema_version` field is the forward-compatibility hook if the format later
needs to evolve.

## Risk / footgun review

- **Page 0-vs-1-based** — mitigated by reusing `list_highlights` (single
  conversion point). Do not re-query the model.
- **Highlights wiped on re-ingest** — expected and unchanged. An export taken
  before a re-ingest keeps the annotations; the live DB drops them. That is
  ADR-024 behavior, not an export concern.
- **Large annotation sets** — `list_highlights` loads all rows for the course
  into memory, same as the existing section/asset queries; the spool already
  spills to disk past 10 MB. No new scaling concern versus today.
