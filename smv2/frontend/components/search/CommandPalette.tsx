"use client";

import { useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";

import { resultHref } from "@/components/search/SearchResults";
import { searchCourse, type SearchResultOut } from "@/lib/api/client";
import { useDialogFocus } from "@/lib/hooks/useDialogFocus";
import { useKeyboardShortcuts } from "@/lib/hooks/useKeyboardShortcuts";

const ACTIONS = [
  { label: "Home", href: "/" },
  { label: "Review", href: "/review" },
  { label: "Flashcards", href: "/flashcards" },
  { label: "Tests", href: "/tests" },
  { label: "Jobs", href: "/jobs" },
  { label: "Settings", href: "/settings" },
  { label: "Search", href: "/search" },
];

function activeCourseFromPath(pathname: string): string | null {
  const match = /^\/course\/([^/]+)/.exec(pathname);
  return match ? decodeURIComponent(match[1]) : null;
}

export default function CommandPalette() {
  const pathname = usePathname() ?? "";
  const router = useRouter();
  const [openPath, setOpenPath] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResultOut[]>([]);
  const activeCourseId = useMemo(() => activeCourseFromPath(pathname), [pathname]);
  const open = openPath === pathname;
  const dialogRef = useDialogFocus<HTMLDivElement>(open);

  function openPalette() {
    setQuery("");
    setResults([]);
    setOpenPath(pathname);
  }

  function closePalette() {
    setOpenPath(null);
  }

  useKeyboardShortcuts(
    {
      "mod+k": (event) => {
        event.preventDefault();
        openPalette();
      },
    },
    true,
  );

  useKeyboardShortcuts(
    {
      escape: (event) => {
        event.preventDefault();
        closePalette();
      },
    },
    open,
  );

  useEffect(() => {
    if (!open) return undefined;
    function handlePointerDown(event: PointerEvent) {
      const node = dialogRef.current;
      if (node && event.target instanceof Node && !node.contains(event.target)) {
        closePalette();
      }
    }
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [dialogRef, open]);

  useEffect(() => {
    if (!open) return undefined;
    const trimmed = query.trim();
    if (!activeCourseId || trimmed.length < 2) return undefined;
    let active = true;
    searchCourse(activeCourseId, trimmed, { limit: 5 }).then(({ data }) => {
      if (active) setResults(data?.items ?? []);
    });
    return () => {
      active = false;
    };
  }, [activeCourseId, open, query]);

  function navigate(href: string) {
    router.push(href);
    closePalette();
  }

  return (
    <>
      <button
        type="button"
        aria-label="Open command palette"
        onClick={openPalette}
        className="flex h-9 w-9 items-center justify-center rounded-md transition-colors hover:bg-foreground/[0.07]"
      >
        <Search aria-hidden="true" className="h-5 w-5" />
      </button>
      {open ? (
        <div
          className="fixed inset-0 z-50 bg-foreground/20 p-4"
          onPointerDown={(event) => {
            if (event.target === event.currentTarget) closePalette();
          }}
        >
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-label="Command palette"
            tabIndex={-1}
            className="mx-auto mt-16 flex w-full max-w-xl flex-col gap-3 rounded-md border border-divider bg-background p-3 shadow-xl"
          >
            <input
              type="search"
              aria-label="Search commands and active course"
              value={query}
              onChange={(event) => {
                const nextQuery = event.target.value;
                setQuery(nextQuery);
                if (nextQuery.trim().length < 2) setResults([]);
              }}
              className="h-11 rounded-md border border-divider bg-background px-3 text-sm"
              placeholder="Search commands or this course"
            />
            <div className="grid grid-cols-2 gap-2">
              {ACTIONS.map((action) => (
                <button
                  key={action.href}
                  type="button"
                  onClick={() => navigate(action.href)}
                  className="rounded-md px-3 py-2 text-left text-sm hover:bg-foreground/[0.07]"
                >
                  {action.label}
                </button>
              ))}
            </div>
            {activeCourseId ? (
              <div className="border-t border-divider pt-2">
                {results.length > 0 ? (
                  <ul className="flex flex-col gap-1">
                    {results.map((result) => (
                      <li key={result.cursor_token}>
                        <button
                          type="button"
                          onClick={() => navigate(resultHref(result))}
                          className="w-full rounded-md px-3 py-2 text-left text-sm hover:bg-foreground/[0.07]"
                        >
                          Open {result.title}
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="px-3 py-2 text-sm text-muted-foreground">
                    Type at least two characters to search the active course.
                  </p>
                )}
              </div>
            ) : (
              <p className="border-t border-divider px-3 py-2 text-sm text-muted-foreground">
                Open the Search page to choose a course.
              </p>
            )}
          </div>
        </div>
      ) : null}
    </>
  );
}
