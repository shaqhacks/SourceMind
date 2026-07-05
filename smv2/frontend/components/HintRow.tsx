export interface HintItem {
  keys: string;
  label: string;
}

export interface HintRowProps {
  hints: HintItem[];
}

/** Slim bottom hint bar: the 3-4 key hints relevant to the current surface. */
export default function HintRow({ hints }: HintRowProps) {
  return (
    <div
      role="note"
      aria-label="Keyboard hints"
      className="flex items-center gap-4 border-t border-border bg-background px-4 py-2 text-xs text-muted-foreground"
    >
      {hints.map((hint) => (
        <span key={hint.keys} className="flex items-center gap-1.5">
          <kbd className="rounded border border-border bg-muted-foreground/10 px-1.5 py-0.5 font-mono">
            {hint.keys}
          </kbd>
          {hint.label}
        </span>
      ))}
      <span className="ml-auto flex items-center gap-1.5">
        <kbd className="rounded border border-border bg-muted-foreground/10 px-1.5 py-0.5 font-mono">?</kbd>
        all shortcuts
      </span>
    </div>
  );
}
