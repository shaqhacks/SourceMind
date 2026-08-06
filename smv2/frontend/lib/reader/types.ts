/**
 * Reader data contract. Components import types from here — never reach
 * into lib/api/client.ts directly — so components/reader/* stay insulated
 * from the API schema (this shape is structurally compatible with the real
 * SectionOut/CourseOut, so the page that calls the API needs no explicit
 * conversion, just matching field names).
 *
 * Body text is deliberately absent here: list_sections never returns
 * body_md (it can be large), so a section's body is fetched lazily via
 * get_section on selection and cached by the reader shell, not carried on
 * this type.
 */

/** Content sections carry the source text; practice/answers sections hold
 * end-of-chapter exercises and their solutions, split out during ingest so
 * they can be surfaced separately (chapter testing page) instead of
 * interleaved into normal reading. */
export type SectionKind = "content" | "practice" | "answers";

export interface ReaderSection {
  id: string;
  title: string;
  order_index: number;
  page_start: number | null;
  page_end: number | null;
  lesson_status: string;
  has_content: boolean;
  word_count: number;
  kind: SectionKind;
  chapter_label: string | null;
  /** The PDF asset this section's original pages live in (null for older/
   * not-yet-migrated data, or a section with no backing asset at all) —
   * backing the reader's "original pages" view. page_start/page_end
   * (above) are per-asset 1-based page numbers, direct pdf.js page
   * numbers, whenever this is non-null. */
  asset_id: string | null;
  source_format?: string | null;
  source_locator?: Record<string, unknown> | null;
}

export interface ReaderCourse {
  id: string;
  title: string;
  sections: ReaderSection[];
}

/** The reader's three-state view. "pages" (the original PDF, via pdf.js)
 * is only available for a PDF section with page provenance. */
export type ViewMode = "source" | "pages" | "lesson";

/** Where to resume: the section last read and how far down it, as a 0..1 fraction. */
export interface ReaderProgress {
  section_id: string | null;
  scroll_pos: number;
}

/** Lazy-load state of a section's body_md, fetched on selection via get_section. */
export type SectionBodyState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; body: string };

/** Per-chapter test aggregate — the pinned shape of list_chapters' own
 * `test_stats` field (null when a chapter has no attempts yet). Shared by
 * Sidebar's "Test" affordance and the chapter test-score bar so both read the
 * same field names once the real endpoint is wired up. */
export interface ChapterTestStats {
  attempts: number;
  best_score: number | null;
  latest_score: number | null;
}
