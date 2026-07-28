"use client";

export interface SelectionContextPillProps {
  /** The exact selected/highlighted passage text this turn will attach to
   * chat — same `exact` string carried on `pendingSelection` (see
   * CourseChatDrawer). */
  exact: string;
  onRemove: () => void;
}

// First ~50 chars of the passage shown in the pill; the full text is only
// ever available via the `title` tooltip.
const SNIPPET_LENGTH = 50;

function wordCount(exact: string): number {
  return exact.trim().split(/\s+/).filter(Boolean).length;
}

function snippet(exact: string): string {
  return exact.length > SNIPPET_LENGTH ? `${exact.slice(0, SNIPPET_LENGTH)}…` : exact;
}

/**
 * Compact pill glued to Chat's composer (passed in as `composerAccessory`)
 * showing the passage that will attach to the next sent message. Replaces
 * the old top-of-panel "Asking about: …" chip — same one-shot lifecycle
 * (CourseChatDrawer owns `pendingSelection`/`onConsumeSelection`), just
 * relocated next to the input it actually affects.
 */
export default function SelectionContextPill({ exact, onRemove }: SelectionContextPillProps) {
  const words = wordCount(exact);
  return (
    <div
      title={exact}
      className="flex items-center justify-between gap-2 rounded-md border border-border bg-surface-raised px-2.5 py-1.5 text-xs text-muted-foreground"
    >
      <span className="truncate">
        <span aria-hidden="true">📄</span> {words} {words === 1 ? "word" : "words"} — &ldquo;{snippet(exact)}&rdquo;
      </span>
      <button
        type="button"
        onClick={onRemove}
        aria-label="Remove context"
        className="shrink-0 rounded-md px-1.5 py-0.5 text-sm hover:bg-muted-foreground/10"
      >
        ✕
      </button>
    </div>
  );
}
