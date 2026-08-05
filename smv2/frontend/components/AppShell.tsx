"use client";

import { useCallback, useEffect, useRef } from "react";
import { usePathname } from "next/navigation";

import AppSidebar from "@/components/AppSidebar";
import { useDialogFocus } from "@/lib/hooks/useDialogFocus";
import { useShellLayout, useShellNavigation } from "@/lib/hooks/useShellLayout";

/**
 * The app's outermost scroll boundary: bounds the whole shell to the real
 * viewport height and never lets it scroll itself — only content areas
 * that opt into their own overflow-y-auto ever scroll (see
 * smv2-frontend-feature's "scroll containers own their overflow, never
 * the document" house rule).
 *
 * Redesign shell: header on top, collapsible app sidebar on the left for
 * top-level surfaces. Routes that manage their own panels (reader's
 * Contents sidebar, review/quiz focus modes) skip the app sidebar — the
 * global header stays so navigation never disappears.
 */
export interface AppShellProps {
  header: React.ReactNode;
  children: React.ReactNode;
}

/** Reader, quiz attempt, chapter test, and review manage their own panels. */
function ownsPanels(pathname: string): boolean {
  return (
    /^\/course\/[^/]+$/.test(pathname) ||
    /^\/course\/[^/]+\/test\/[^/]+$/.test(pathname) ||
    /^\/course\/[^/]+\/chapter\/[^/]+\/test$/.test(pathname) ||
    pathname === "/review"
  );
}

export default function AppShell({ header, children }: AppShellProps) {
  const pathname = usePathname() ?? "";
  const withSidebar = !ownsPanels(pathname);
  const layout = useShellLayout();
  const transientNavigation = layout !== "desktop";
  const { open, closeNavigation } = useShellNavigation();
  const drawerOpen = transientNavigation && open;
  const drawerRef = useDialogFocus<HTMLDivElement>(drawerOpen);
  const drawerShellRef = useRef<HTMLDivElement>(null);

  const closeDrawer = useCallback(() => {
    closeNavigation();
  }, [closeNavigation]);

  useEffect(() => {
    closeNavigation();
  }, [pathname, closeNavigation]);

  useEffect(() => {
    if (!transientNavigation) closeNavigation();
  }, [transientNavigation, closeNavigation]);

  useEffect(() => {
    if (!drawerOpen) return undefined;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") closeDrawer();
    }

    function handlePointerDown(event: PointerEvent) {
      if (
        drawerShellRef.current &&
        !drawerShellRef.current.contains(event.target as Node)
      ) {
        closeDrawer();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [drawerOpen, closeDrawer]);

  return (
    <div data-layout={layout} className="flex h-dvh flex-col overflow-hidden">
      {header}
      <div className="flex min-h-0 flex-1">
        {withSidebar && !transientNavigation ? <AppSidebar /> : null}
        <main
          id="main-content"
          tabIndex={-1}
          className="flex min-h-0 flex-1 flex-col overflow-x-hidden overflow-y-auto"
        >
          {children}
        </main>
      </div>
      {drawerOpen && (
        <div
          className="fixed inset-0 z-50 bg-foreground/30"
          aria-hidden={false}
        >
          <div
            ref={drawerShellRef}
            role="dialog"
            aria-modal="true"
            aria-label="App navigation"
            data-layout={layout}
            className="flex h-full w-[min(22rem,88vw)] flex-col border-r border-divider bg-background shadow-lg"
          >
            <div
              ref={drawerRef}
              tabIndex={-1}
              className="flex min-h-0 flex-1 flex-col"
            >
              <div className="flex items-center justify-between gap-3 border-b border-divider px-4 py-3">
                <p className="font-heading text-lg text-accent">SourceMind</p>
                <button
                  type="button"
                  onClick={closeDrawer}
                  aria-label="Close navigation"
                  className="min-h-11 rounded-md border border-border bg-surface-raised px-3 py-2 text-sm font-medium transition-colors hover:bg-foreground/[0.07]"
                >
                  Close
                </button>
              </div>
              <AppSidebar variant="drawer" />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
