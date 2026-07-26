"use client";

import { useEffect, useMemo, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import Markdown from "@/components/Markdown";
import { listHighlights, listNotes, type HighlightOut, type NoteOut } from "@/lib/api/client";
import { describeError, type FetchError } from "@/lib/api/errors";
import { useDialogFocus } from "@/lib/hooks/useDialogFocus";
import { useKeyboardShortcuts } from "@/lib/hooks/useKeyboardShortcuts";

/** Just enough of a section to group/label/order by — deliberately narrower
 * than SectionOut/ReaderSection so this component doesn't need to import
 * either; CourseReader's own `sections` (whichever of those two types it
 * currently holds) is structurally compatible with this. */
export interface NotesPanelSection {
  id: string;
  title: string;
  order_index: number;
}

export interface NotesPanelProps {
  courseId: string;
  open: boolean;
  /** Course's sections, used only for grouping/labeling/ordering — see
   * NotesPanelSection. Passed down rather than re-fetched here (CourseReader
   * already has them loaded). */
  sections: NotesPanelSection[];
  onClose: () => void;
  /** Hands back both the highlight's section (for goToSection) and its
   * surface — a `"pdf"` note only ever painted in Pages view (see
   * useHighlightPainter's surface filter), so the caller needs the surface
   * to switch the reader into that view as part of navigating there. */
  onNavigate: (sectionId: string, surface: HighlightOut["surface"]) => void;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | { kind: "ready"; highlights: HighlightOut[]; notes: NoteOut[] };

interface SectionGroup {
  sectionId: string;
  title: string;
  orderIndex: number;
  highlights: HighlightOut[];
  notes: NoteOut[];
}

// Long selections still need to fit on one line-ish quote — this isn't a
// hard content limit anywhere else, just this list's own display truncation.
const EXACT_TRUNCATE_LENGTH = 140;

function truncateExact(text: string): string {
  if (text.length <= EXACT_TRUNCATE_LENGTH) return text;
  return `${text.slice(0, EXACT_TRUNCATE_LENGTH).trimEnd()}…`;
}

/**
 * Groups a COURSE-WIDE highlight AND note list by section, ordered by the
 * section's own order_index (reading order), each group's items ordered by
 * created_at (oldest first — the order they were added). A highlight or note
 * whose section_id isn't found in `sections` (e.g. a since-deleted/merged
 * section from an outline edit) still gets its own group, sorted last — never
 * dropped, per the "never hidden, never auto-deleted" rule this panel upholds.
 */
function groupBySection(
  highlights: HighlightOut[],
  notes: NoteOut[],
  sections: NotesPanelSection[],
): SectionGroup[] {
  const sectionById = new Map(sections.map((section) => [section.id, section]));
  const groups = new Map<string, SectionGroup>();

  const ensureGroup = (sectionId: string): SectionGroup => {
    let group = groups.get(sectionId);
    if (!group) {
      const section = sectionById.get(sectionId);
      group = {
        sectionId,
        title: section?.title ?? "Unknown section",
        orderIndex: section?.order_index ?? Number.MAX_SAFE_INTEGER,
        highlights: [],
        notes: [],
      };
      groups.set(sectionId, group);
    }
    return group;
  };

  for (const item of highlights) ensureGroup(item.section_id).highlights.push(item);
  for (const item of notes) ensureGroup(item.section_id).notes.push(item);

  for (const group of groups.values()) {
    group.highlights.sort((a, b) => a.created_at.localeCompare(b.created_at));
    group.notes.sort((a, b) => a.created_at.localeCompare(b.created_at));
  }

  return Array.from(groups.values()).sort((a, b) => a.orderIndex - b.orderIndex);
}

function HighlightRow({
  highlight,
  onNavigate,
}: {
  highlight: HighlightOut;
  onNavigate: (sectionId: string, surface: HighlightOut["surface"]) => void;
}) {
  return (
    <li className="overflow-hidden rounded-md border border-divider bg-surface-raised">
      <button
        type="button"
        onClick={() => onNavigate(highlight.section_id, highlight.surface)}
        className="flex w-full items-start gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-foreground/[0.05]"
      >
        <span
          aria-hidden="true"
          className="mt-1 h-3 w-3 shrink-0 rounded-full border border-border"
          style={{ backgroundColor: `var(--highlight-${highlight.color})` }}
        />
        {/* PDF highlights only ever paint in Pages view (out of scope:
         * cross-surface rendering) — this badge is the only place in the
         * course-wide list that tells them apart from a source-view note,
         * so it folds the page number in rather than repeating it via the
         * source-only "· p.N" suffix below. */}
        {highlight.surface === "pdf" && (
          <span className="mt-0.5 shrink-0 rounded-[6px] bg-neutral-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-neutral-800">
            PDF{highlight.page !== null ? ` p.${highlight.page}` : ""}
          </span>
        )}
        <span className="min-w-0 flex-1 italic text-muted-foreground">
          &ldquo;{truncateExact(highlight.exact)}&rdquo;
          {highlight.surface === "source" && highlight.page !== null && (
            <span className="ml-1 not-italic text-xs text-muted-foreground">· p.{highlight.page}</span>
          )}
        </span>
      </button>
      {/* Outside the button — Markdown can render block elements (e.g. a
       * paragraph, a link), which can't legally nest inside a <button>. */}
      <div className="border-t border-divider px-3 py-2 pl-8 text-sm">
        {highlight.note_md ? (
          <Markdown>{highlight.note_md}</Markdown>
        ) : (
          <span className="text-xs text-muted-foreground">No note</span>
        )}
      </div>
    </li>
  );
}

/** A standalone positional margin note (no quoted passage — just the note
 * text and which PDF page it sits beside). Clicking navigates to that section
 * in Pages view, same as a pdf highlight. */
function NoteRow({
  note,
  onNavigate,
}: {
  note: NoteOut;
  onNavigate: (sectionId: string, surface: HighlightOut["surface"]) => void;
}) {
  return (
    <li className="overflow-hidden rounded-md border border-divider bg-surface-raised">
      <button
        type="button"
        onClick={() => onNavigate(note.section_id, "pdf")}
        className="flex w-full items-start gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-foreground/[0.05]"
      >
        <span className="mt-0.5 shrink-0 rounded-[6px] bg-neutral-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-neutral-800">
          PDF p.{note.page}
        </span>
        <span className="min-w-0 flex-1 text-muted-foreground">Page note</span>
      </button>
      {/* Outside the button — Markdown can render block elements. */}
      <div className="border-t border-divider px-3 py-2 pl-8 text-sm">
        <Markdown>{note.note_md}</Markdown>
      </div>
    </li>
  );
}

/**
 * Course-wide list of every highlight + its note, grouped by section for
 * scannability, mirroring CourseChatDrawer's slide-over open/close/dismiss
 * idiom (always a fixed overlay here — unlike chat, this panel doesn't need
 * a docked wide-viewport mode; it's a glance-and-dismiss list, not a
 * persistent companion). Clicking a row hands its section_id and surface to
 * `onNavigate` (CourseReader's own section switch, which also flips to Pages
 * view for a `"pdf"` note) and lets the caller decide whether to also close
 * the panel.
 *
 * Fetches fresh every time it opens (mount-effect gated on `open`, same
 * "refetch on open" intent as CourseChatDrawer's inner Chat component
 * mounting fresh) — a note edited via HighlightEditPopover while this panel
 * was closed must show up next time it opens, not a stale snapshot.
 */
export default function NotesPanel({ courseId, open, sections, onClose, onNavigate }: NotesPanelProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [reloadToken, setReloadToken] = useState(0);

  // Own scope while open, same pattern as CourseChatDrawer — sits on top of
  // the reader's own shortcut scope so arrow/j/k/s/c/o don't fire behind an
  // open panel.
  useKeyboardShortcuts({ escape: onClose }, open);
  const panelRef = useDialogFocus<HTMLDivElement>(open, { trap: false });

  useEffect(() => {
    if (!open) return undefined;
    let active = true;
    // No synchronous "reset to loading" here (matches useHighlights'/
    // CourseReaderClient's own fetch-effect convention in this codebase,
    // and avoids the cascading-render setState-in-effect footgun): a
    // reopen briefly shows the PREVIOUS fetch's list while the new one is
    // in flight, then swaps once it resolves, rather than flashing back to
    // a loading state the user just watched resolve moments ago.
    Promise.all([listHighlights(courseId), listNotes(courseId)]).then(([hl, nt]) => {
      if (!active) return;
      if (hl.data && nt.data) {
        setState({ kind: "ready", highlights: hl.data, notes: nt.data });
      } else {
        const failedStatus = hl.data ? nt.status : hl.status;
        setState({ kind: "error", error: describeError(failedStatus, "Loading notes") });
      }
    });
    return () => {
      active = false;
    };
  }, [open, courseId, reloadToken]);

  const groups = useMemo(
    () => (state.kind === "ready" ? groupBySection(state.highlights, state.notes, sections) : []),
    [state, sections],
  );

  if (!open) return null;

  return (
    <div
      ref={panelRef}
      role="complementary"
      aria-label="Course notes"
      tabIndex={-1}
      className="fixed inset-y-0 right-0 z-40 flex w-[340px] max-w-[90vw] flex-col border-l border-divider bg-background shadow-lg"
    >
      <div className="flex items-center justify-between gap-2 border-b border-divider px-4 py-3">
        <h2 className="text-[13px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
          Notes
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close notes"
          className="rounded-md border border-border bg-surface-raised px-2.5 py-1 text-xs font-medium transition-colors hover:bg-foreground/[0.07]"
        >
          Close
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {state.kind === "loading" && (
          <p className="p-4 text-sm text-muted-foreground">Loading notes…</p>
        )}
        {state.kind === "error" && (
          <div className="p-4">
            <ErrorBanner
              status={state.error.status}
              message={state.error.message}
              onRetry={() => setReloadToken((token) => token + 1)}
            />
          </div>
        )}
        {state.kind === "ready" && groups.length === 0 && (
          <p className="p-4 text-sm text-muted-foreground">
            No highlights or notes yet — select text in a chapter, or add a page note in the
            original pages.
          </p>
        )}
        {state.kind === "ready" &&
          groups.map((group) => (
            <section key={group.sectionId} className="border-b border-divider px-3 py-3 last:border-b-0">
              <h3 className="mb-2 truncate text-[11px] font-bold uppercase tracking-[0.06em] text-neutral-600">
                {group.title}
              </h3>
              <ul className="flex flex-col gap-2">
                {group.highlights.map((item) => (
                  <HighlightRow key={item.id} highlight={item} onNavigate={onNavigate} />
                ))}
                {group.notes.map((item) => (
                  <NoteRow key={item.id} note={item} onNavigate={onNavigate} />
                ))}
              </ul>
            </section>
          ))}
      </div>
    </div>
  );
}
