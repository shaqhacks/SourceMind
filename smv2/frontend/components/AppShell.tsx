/**
 * The app's outermost scroll boundary: bounds the whole shell to the real
 * viewport height and never lets it scroll itself — only content areas
 * that opt into their own overflow-y-auto ever scroll (see
 * smv2-frontend-feature's "scroll containers own their overflow, never
 * the document" house rule). Extracted out of app/layout.tsx so it's
 * unit-testable on its own — RTL can't cleanly mount RootLayout's real
 * <html>/<body>/next/font wrapper, same reason SiteHeader/SkipToMainLink
 * were both extracted.
 *
 * `header` sits at its natural height; `children` gets the remaining
 * space via flex-1 (bounded now that this wrapper itself is height-bound)
 * plus its own overflow-y-auto as a fallback scroll container for any
 * route that doesn't manage its own internal scrolling (e.g. the
 * dashboard's course list) — the reader route's own Sidebar/ReadingColumn
 * manage their own overflow internally and never need this fallback to
 * actually engage.
 */
export interface AppShellProps {
  header: React.ReactNode;
  children: React.ReactNode;
}

export default function AppShell({ header, children }: AppShellProps) {
  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      {header}
      <main
        id="main-content"
        tabIndex={-1}
        className="flex min-h-0 flex-1 flex-col overflow-y-auto"
      >
        {children}
      </main>
    </div>
  );
}
