"use client";

import { useEffect, useMemo, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import Markdown from "@/components/Markdown";
import { listHighlights, type HighlightOut } from "@/lib/api/client";
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
  | { kind: "ready"; highlights: HighlightOut[] };

interface HighlightGroup {
  sectionId: string;
  title: string;
  orderIndex: number;
  highlights: HighlightOut[];
}

// Long selections still need to fit on one line-ish quote — this isn't a
// hard content limit anywhere else, just this list's own display truncation.
const EXACT_TRUNCATE_LENGTH = 140;

function truncateExact(text: string): string {
  if (text.length <= EXACT_TRUNCATE_LENGTH) return text;
  return `${text.slice(0, EXACT_TRUNCATE_LENGTH).trimEnd()}…`;
}

/**
 * Groups a COURSE-WIDE highlight list by section, ordered by the section's
 * own order_index (reading order), with each group's highlights ordered by
 * created_at (oldest first — the order they were added while reading
 * through that section). A highlight whose section_id isn't found in
 * `sections` (e.g. a since-deleted/merged section from an outline edit)
 * still gets its own group, sorted last — never dropped, per the "never
 * hidden, never auto-deleted" rule this panel exists to uphold.
 */
function groupBySection(highlights: HighlightOut[], sections: NotesPanelSection[]): HighlightGroup[] {
  const sectionById = new Map(sections.map((section) => [section.id, section]));
  const groups = new Map<string, HighlightGroup>();

  for (const item of highlights) {
    let group = groups.get(item.section_id);
    if (!group) {
      const section = sectionById.get(item.section_id);
      group = {
        sectionId: item.section_id,
        title: section?.title ?? "Unknown section",
        orderIndex: section?.order_index ?? Number.MAX_SAFE_INTEGER,
        highlights: [],
      };
      groups.set(item.section_id, group);
    }
    group.highlights.push(item);
  }

  for (const group of groups.values()) {
    group.highlights.sort((a, b) => a.created_at.localeCompare(b.created_at));
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
    <li className="overflow-hidden rounded-md border border-border">
      <button
        type="button"
        onClick={() => onNavigate(highlight.section_id, highlight.surface)}
        className="flex w-full items-start gap-2 px-3 py-2 text-left text-sm hover:bg-muted-foreground/10"
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
          <span className="mt-0.5 shrink-0 rounded-full border border-border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
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
      <div className="border-t border-border px-3 py-2 pl-8 text-sm">
        {highlight.note_md ? (
          <Markdown>{highlight.note_md}</Markdown>
        ) : (
          <span className="text-xs text-muted-foreground">No note</span>
        )}
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
    listHighlights(courseId).then(({ data, status }) => {
      if (!active) return;
      if (data) {
        setState({ kind: "ready", highlights: data });
      } else {
        setState({ kind: "error", error: describeError(status, "Loading notes") });
      }
    });
    return () => {
      active = false;
    };
  }, [open, courseId, reloadToken]);

  const groups = useMemo(
    () => (state.kind === "ready" ? groupBySection(state.highlights, sections) : []),
    [state, sections],
  );

  if (!open) return null;

  return (
    <div
      ref={panelRef}
      role="complementary"
      aria-label="Course notes"
      tabIndex={-1}
      className="fixed inset-y-0 right-0 z-40 flex w-96 max-w-[90vw] flex-col border-l border-border bg-background shadow-xl"
    >
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Notes</h2>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close notes"
          className="rounded-md border border-border px-2 py-1 text-sm"
        >
          Close
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
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
            No highlights yet — select text in a chapter to add one.
          </p>
        )}
        {state.kind === "ready" &&
          groups.map((group) => (
            <section key={group.sectionId} className="border-b border-border px-3 py-3 last:border-b-0">
              <h3 className="mb-2 truncate text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {group.title}
              </h3>
              <ul className="flex flex-col gap-2">
                {group.highlights.map((item) => (
                  <HighlightRow key={item.id} highlight={item} onNavigate={onNavigate} />
                ))}
              </ul>
            </section>
          ))}
      </div>
    </div>
  );
}
