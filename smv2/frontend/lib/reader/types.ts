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

export interface ReaderSection {
  id: string;
  title: string;
  order_index: number;
  page_start: number | null;
  page_end: number | null;
  lesson_status: string;
  has_content: boolean;
  word_count: number;
}

export interface ReaderCourse {
  id: string;
  title: string;
  sections: ReaderSection[];
}

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
