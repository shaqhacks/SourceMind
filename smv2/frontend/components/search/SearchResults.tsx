import Link from "next/link";

import type { SearchResultOut } from "@/lib/api/client";

function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-");
}

function locatorText(result: SearchResultOut): string {
  const parts = [
    result.source_locator.chapter,
    result.source_locator.heading,
    result.source_locator.slide ? `slide ${result.source_locator.slide}` : null,
    result.source_locator.page ? `p. ${result.source_locator.page}` : null,
  ];
  return parts.filter(Boolean).join(" · ");
}

export function resultHref(result: SearchResultOut): string {
  const section = result.section_id ? `?section=${encodeURIComponent(result.section_id)}` : "";
  const hash = result.source_locator.heading ? `#${slugify(result.source_locator.heading)}` : "";
  return `/course/${encodeURIComponent(result.course_id)}${section}${hash}`;
}

export interface SearchResultsProps {
  courseTitle: string;
  query: string;
  loading: boolean;
  error: string | null;
  results: SearchResultOut[];
  nextCursor: string | null;
  hasSearched: boolean;
  onLoadMore: () => void;
}

export default function SearchResults({
  courseTitle,
  query,
  loading,
  error,
  results,
  nextCursor,
  hasSearched,
  onLoadMore,
}: SearchResultsProps) {
  if (loading && results.length === 0) {
    return <p className="text-sm text-muted-foreground">Searching course text...</p>;
  }

  if (error) {
    return (
      <div role="alert" className="rounded-md border border-danger/30 bg-danger/10 p-4 text-sm">
        {error}
      </div>
    );
  }

  if (!hasSearched) {
    return (
      <div className="rounded-md border border-dashed border-divider p-6 text-sm text-muted-foreground">
        Search one course at a time. Results stay local to the selected course.
      </div>
    );
  }

  if (results.length === 0) {
    return (
      <p className="rounded-md border border-divider p-6 text-sm text-muted-foreground">
        No matches in {courseTitle} for &ldquo;{query}&rdquo;.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <ol className="flex flex-col gap-3">
        {results.map((result) => (
          <li key={result.cursor_token}>
            <article
              aria-label={result.title}
              className="rounded-md border border-divider bg-surface-raised p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="font-heading text-lg">{result.title}</h2>
                  <p className="mt-1 text-xs uppercase tracking-[0.08em] text-muted-foreground">
                    {result.doc_type}
                  </p>
                </div>
                <Link
                  href={resultHref(result)}
                  className="text-sm font-medium text-accent hover:underline"
                >
                  Open section
                </Link>
              </div>
              {locatorText(result) ? (
                <p className="mt-3 text-sm text-muted-foreground">{locatorText(result)}</p>
              ) : null}
              <p className="mt-3 text-sm leading-6">{result.excerpt_md}</p>
            </article>
          </li>
        ))}
      </ol>
      {nextCursor ? (
        <button
          type="button"
          onClick={onLoadMore}
          disabled={loading}
          className="self-start rounded-md border border-divider px-4 py-2 text-sm font-medium hover:bg-foreground/[0.07] disabled:opacity-60"
        >
          {loading ? "Loading more..." : "Load more results"}
        </button>
      ) : null}
    </div>
  );
}
