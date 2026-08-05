import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CourseSearchClient from "@/components/search/CourseSearchClient";
import { listCourses, searchCourse } from "@/lib/api/client";
import type { ApiResult, SearchResultsOut } from "@/lib/api/client";

vi.mock("@/lib/api/client", () => ({
  listCourses: vi.fn(),
  searchCourse: vi.fn(),
}));

const mockedListCourses = vi.mocked(listCourses);
const mockedSearchCourse = vi.mocked(searchCourse);

const courses = [
  {
    id: "course-1",
    title: "Biology 101",
    status: "ready",
    section_count: 2,
    failed_asset_count: 0,
    is_sample: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    progress: null,
  },
  {
    id: "course-2",
    title: "History 202",
    status: "ready",
    section_count: 1,
    failed_asset_count: 0,
    is_sample: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    progress: null,
  },
];

function ok<T>(data: T): ApiResult<T> {
  return { status: 200, ok: true, data };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((innerResolve, innerReject) => {
    resolve = innerResolve;
    reject = innerReject;
  });
  return { promise, resolve, reject };
}

function result(overrides = {}) {
  return {
    doc_type: "section" as const,
    course_id: "course-1",
    section_id: "sec-1",
    asset_id: "asset-1",
    title: "Cell membranes",
    excerpt_md: "Membranes keep &lt;script&gt; out of cells.",
    source_locator: { page: 12, heading: "Transport Proteins", chapter: "Chapter 2", slide: null },
    score: 9.7,
    cursor_token: "cursor-1",
    ...overrides,
  };
}

function searchPayload(overrides = {}) {
  return {
    backend: "fts5" as const,
    next_cursor: null,
    sanitized_excerpts: true,
    items: [result()],
    ...overrides,
  };
}

describe("CourseSearchClient", () => {
  beforeEach(() => {
    mockedListCourses.mockResolvedValue(ok(courses));
    mockedSearchCourse.mockResolvedValue(ok(searchPayload()));
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("shows the empty state before a query", async () => {
    render(<CourseSearchClient />);

    expect(await screen.findByRole("combobox", { name: "Course" })).toHaveValue("course-1");
    expect(screen.getByText(/search one course at a time/i)).toBeInTheDocument();
    expect(mockedSearchCourse).not.toHaveBeenCalled();
  });

  it("renders results with locator text and section navigation", async () => {
    const user = userEvent.setup();
    render(<CourseSearchClient />);

    await user.type(await screen.findByRole("searchbox", { name: "Search course text" }), "membrane");
    await user.click(screen.getByRole("button", { name: "Search" }));

    const result = await screen.findByRole("article", { name: "Cell membranes" });
    expect(within(result).getByText("Chapter 2 · Transport Proteins · p. 12")).toBeInTheDocument();
    expect(within(result).getByText("Membranes keep &lt;script&gt; out of cells.")).toBeInTheDocument();
    expect(result.innerHTML).not.toContain("<script>");
    expect(within(result).getByRole("link", { name: "Open section" })).toHaveAttribute(
      "href",
      "/course/course-1?section=sec-1#transport-proteins",
    );
  });

  it("preserves course selection across a rerender", async () => {
    const { rerender } = render(<CourseSearchClient />);
    const user = userEvent.setup();

    await user.selectOptions(await screen.findByRole("combobox", { name: "Course" }), "course-2");
    rerender(<CourseSearchClient />);

    expect(screen.getByRole("combobox", { name: "Course" })).toHaveValue("course-2");
  });

  it("submits the search form from the keyboard", async () => {
    const user = userEvent.setup();
    render(<CourseSearchClient />);

    await user.type(await screen.findByRole("searchbox", { name: "Search course text" }), "osmosis{Enter}");

    await waitFor(() => {
      expect(mockedSearchCourse).toHaveBeenCalledWith("course-1", "osmosis", {
        documentTypes: [],
        limit: 10,
      });
    });
  });

  it("shows empty-results copy", async () => {
    const user = userEvent.setup();
    mockedSearchCourse.mockResolvedValue(ok(searchPayload({ items: [], next_cursor: null })));
    render(<CourseSearchClient />);

    await user.type(await screen.findByRole("searchbox", { name: "Search course text" }), "photosynthesis");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText(/no matches in Biology 101/i)).toBeInTheDocument();
  });

  it("loads the next page with the returned cursor and selected filters", async () => {
    const user = userEvent.setup();
    mockedSearchCourse
      .mockResolvedValueOnce(ok(searchPayload({ next_cursor: "cursor-2" })))
      .mockResolvedValueOnce(ok(searchPayload({ next_cursor: null })));
    render(<CourseSearchClient />);

    await user.click(await screen.findByRole("checkbox", { name: "Lessons" }));
    await user.type(screen.getByRole("searchbox", { name: "Search course text" }), "transport");
    await user.click(screen.getByRole("button", { name: "Search" }));
    await user.click(await screen.findByRole("button", { name: "Load more results" }));

    expect(mockedSearchCourse).toHaveBeenLastCalledWith("course-1", "transport", {
      documentTypes: ["lesson"],
      cursor: "cursor-2",
      limit: 10,
    });
  });

  it("ignores an older search response that resolves after the latest search", async () => {
    const user = userEvent.setup();
    const first = deferred<ApiResult<SearchResultsOut>>();
    const second = deferred<ApiResult<SearchResultsOut>>();
    mockedSearchCourse
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    render(<CourseSearchClient />);

    await user.type(await screen.findByRole("searchbox", { name: "Search course text" }), "alpha");
    await user.click(screen.getByRole("button", { name: "Search" }));
    await user.clear(screen.getByRole("searchbox", { name: "Search course text" }));
    await user.type(screen.getByRole("searchbox", { name: "Search course text" }), "beta");
    await user.click(screen.getByRole("button", { name: "Search" }));

    second.resolve(
      ok(searchPayload({ items: [result({ title: "Beta result", cursor_token: "beta" })] })),
    );
    expect(await screen.findByRole("article", { name: "Beta result" })).toBeInTheDocument();

    first.resolve(
      ok(searchPayload({ items: [result({ title: "Alpha result", cursor_token: "alpha" })] })),
    );
    await waitFor(() => {
      expect(screen.queryByRole("article", { name: "Alpha result" })).not.toBeInTheDocument();
    });
  });

  it("keeps the latest loading state when a stale request settles", async () => {
    const user = userEvent.setup();
    const first = deferred<ApiResult<SearchResultsOut>>();
    const second = deferred<ApiResult<SearchResultsOut>>();
    mockedSearchCourse
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    render(<CourseSearchClient />);

    await user.type(await screen.findByRole("searchbox", { name: "Search course text" }), "alpha");
    await user.click(screen.getByRole("button", { name: "Search" }));
    await user.clear(screen.getByRole("searchbox", { name: "Search course text" }));
    await user.type(screen.getByRole("searchbox", { name: "Search course text" }), "beta");
    await user.click(screen.getByRole("button", { name: "Search" }));

    first.resolve(ok(searchPayload({ items: [result({ title: "Alpha result" })] })));

    await waitFor(() => {
      expect(screen.getByText("Searching course text...")).toBeInTheDocument();
    });
    second.resolve(ok(searchPayload({ items: [result({ title: "Beta result" })] })));
    expect(await screen.findByRole("article", { name: "Beta result" })).toBeInTheDocument();
  });

  it("paginates with the submitted params even after live inputs change and skips duplicate rows", async () => {
    const user = userEvent.setup();
    mockedSearchCourse
      .mockResolvedValueOnce(
        ok(
          searchPayload({
            next_cursor: "cursor-2",
            items: [result({ title: "Page one", cursor_token: "shared" })],
          }),
        ),
      )
      .mockResolvedValueOnce(
        ok(
          searchPayload({
            next_cursor: null,
            items: [
              result({ title: "Page one duplicate", cursor_token: "shared" }),
              result({ title: "Page two", cursor_token: "page-two" }),
            ],
          }),
        ),
      );
    render(<CourseSearchClient />);

    await user.click(await screen.findByRole("checkbox", { name: "Lessons" }));
    await user.type(screen.getByRole("searchbox", { name: "Search course text" }), "transport");
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByRole("article", { name: "Page one" })).toBeInTheDocument();

    await user.clear(screen.getByRole("searchbox", { name: "Search course text" }));
    await user.type(screen.getByRole("searchbox", { name: "Search course text" }), "edited live query");
    await user.click(screen.getByRole("checkbox", { name: "Lessons" }));
    await user.click(screen.getByRole("button", { name: "Load more results" }));

    expect(mockedSearchCourse).toHaveBeenLastCalledWith("course-1", "transport", {
      documentTypes: ["lesson"],
      cursor: "cursor-2",
      limit: 10,
    });
    expect(await screen.findByRole("article", { name: "Page two" })).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: "Page one duplicate" })).not.toBeInTheDocument();
  });

  it("invalidates in-flight search work when the course changes", async () => {
    const user = userEvent.setup();
    const staleSuccess = deferred<ApiResult<SearchResultsOut>>();
    const staleError = deferred<ApiResult<SearchResultsOut>>();
    mockedSearchCourse
      .mockReturnValueOnce(staleSuccess.promise)
      .mockReturnValueOnce(staleError.promise)
      .mockResolvedValueOnce(
        ok(
          searchPayload({
            items: [
              result({
                course_id: "course-2",
                title: "History result",
                cursor_token: "history",
              }),
            ],
          }),
        ),
      );
    render(<CourseSearchClient />);

    await user.type(await screen.findByRole("searchbox", { name: "Search course text" }), "biology");
    await user.click(screen.getByRole("button", { name: "Search" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Course" }), "course-2");

    staleSuccess.resolve(
      ok(searchPayload({ items: [result({ title: "Stale biology", cursor_token: "stale" })] })),
    );

    await waitFor(() => {
      expect(screen.queryByRole("article", { name: "Stale biology" })).not.toBeInTheDocument();
      expect(screen.queryByText("Searching course text...")).not.toBeInTheDocument();
      expect(screen.getByText(/search one course at a time/i)).toBeInTheDocument();
    });

    await user.type(screen.getByRole("searchbox", { name: "Search course text" }), "history");
    await user.click(screen.getByRole("button", { name: "Search" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Course" }), "course-1");
    staleError.reject(new Error("old course failed"));

    await waitFor(() => {
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(screen.queryByText("Searching course text...")).not.toBeInTheDocument();
    });

    await user.selectOptions(screen.getByRole("combobox", { name: "Course" }), "course-2");
    await user.clear(screen.getByRole("searchbox", { name: "Search course text" }));
    await user.type(screen.getByRole("searchbox", { name: "Search course text" }), "history");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByRole("article", { name: "History result" })).toBeInTheDocument();
    expect(mockedSearchCourse).toHaveBeenLastCalledWith("course-2", "history", {
      documentTypes: [],
      limit: 10,
    });
  });
});
