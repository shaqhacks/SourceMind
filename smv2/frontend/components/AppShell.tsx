"use client";

import { usePathname } from "next/navigation";

import AppSidebar from "@/components/AppSidebar";

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

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      {header}
      <div className="flex min-h-0 flex-1">
        {withSidebar ? <AppSidebar /> : null}
        <main
          id="main-content"
          tabIndex={-1}
          className="flex min-h-0 flex-1 flex-col overflow-y-auto"
        >
          {children}
        </main>
      </div>
    </div>
  );
}
