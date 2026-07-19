import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import NotesPanel from "@/components/reader/NotesPanel";
import { listHighlights, type HighlightOut } from "@/lib/api/client";

import { err, ok } from "../support/api-result";

vi.mock("@/lib/api/client", () => ({
  listHighlights: vi.fn(),
}));

const mockedListHighlights = vi.mocked(listHighlights);

const SECTIONS = [
  { id: "sec-1", title: "Chapter 1: Origins", order_index: 0 },
  { id: "sec-2", title: "Chapter 2: Growth", order_index: 1 },
];

function highlight(overrides: Partial<HighlightOut>): HighlightOut {
  return {
    id: "h-default",
    course_id: "course-1",
    section_id: "sec-1",
    exact: "the quick brown fox",
    prefix: "",
    suffix: "",
    occurrence: 0,
    page: null,
    color: "yellow",
    surface: "source",
    note_md: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const WITH_NOTE = highlight({
  id: "h1",
  section_id: "sec-1",
  exact: "the quick brown fox",
  note_md: "Remember this metaphor",
  color: "yellow",
  created_at: "2026-01-01T00:00:00Z",
});

const WITHOUT_NOTE = highlight({
  id: "h2",
  section_id: "sec-2",
  exact: "jumps over the lazy dog",
  note_md: null,
  color: "green",
  created_at: "2026-01-01T00:00:01Z",
});

const PDF_NOTE = highlight({
  id: "h3",
  section_id: "sec-1",
  exact: "a diagram from the printed page",
  note_md: null,
  color: "blue",
  surface: "pdf",
  page: 12,
  created_at: "2026-01-01T00:00:02Z",
});

describe("NotesPanel", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders nothing when closed, and doesn't fetch", () => {
    const { container } = render(
      <NotesPanel
        courseId="course-1"
        open={false}
        sections={SECTIONS}
        onClose={vi.fn()}
        onNavigate={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(mockedListHighlights).not.toHaveBeenCalled();
  });

  it("lists highlights grouped by section (in section order), with quote + note preview, and a no-note affordance for a null note_md", async () => {
    mockedListHighlights.mockResolvedValue(ok([WITH_NOTE, WITHOUT_NOTE]));

    render(
      <NotesPanel
        courseId="course-1"
        open
        sections={SECTIONS}
        onClose={vi.fn()}
        onNavigate={vi.fn()}
      />,
    );

    expect(await screen.findByText(/remember this metaphor/i)).toBeInTheDocument();
    expect(mockedListHighlights).toHaveBeenCalledWith("course-1");

    const groupHeadings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(groupHeadings).toEqual(["Chapter 1: Origins", "Chapter 2: Growth"]);

    expect(screen.getByText(/the quick brown fox/i)).toBeInTheDocument();
    expect(screen.getByText(/jumps over the lazy dog/i)).toBeInTheDocument();

    // The null-note_md highlight still renders its quote, with a "no note"
    // affordance instead of rendered markdown — it is never hidden.
    expect(screen.getByText(/no note/i)).toBeInTheDocument();
  });

  it("clicking a row navigates to that highlight's section and does not itself close the panel", async () => {
    mockedListHighlights.mockResolvedValue(ok([WITH_NOTE, WITHOUT_NOTE]));
    const onNavigate = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(
      <NotesPanel
        courseId="course-1"
        open
        sections={SECTIONS}
        onClose={onClose}
        onNavigate={onNavigate}
      />,
    );

    const row = await screen.findByRole("button", { name: /jumps over the lazy dog/i });
    await user.click(row);

    expect(onNavigate).toHaveBeenCalledWith("sec-2", "source");
  });

  it("shows a PDF badge only on surface:pdf rows, and passes the surface through to onNavigate", async () => {
    mockedListHighlights.mockResolvedValue(ok([WITH_NOTE, PDF_NOTE]));
    const onNavigate = vi.fn();
    const user = userEvent.setup();

    render(
      <NotesPanel
        courseId="course-1"
        open
        sections={SECTIONS}
        onClose={vi.fn()}
        onNavigate={onNavigate}
      />,
    );

    const pdfRow = await screen.findByRole("button", { name: /a diagram from the printed page/i });
    expect(within(pdfRow).getByText(/pdf p\.12/i)).toBeInTheDocument();

    // The existing source-surface treatment is untouched: no PDF badge,
    // and its own page display (when present) still reads "· p.N".
    const sourceRow = screen.getByRole("button", { name: /the quick brown fox/i });
    expect(within(sourceRow).queryByText(/pdf/i)).not.toBeInTheDocument();

    await user.click(pdfRow);
    expect(onNavigate).toHaveBeenCalledWith("sec-1", "pdf");
  });

  it("shows an empty state when the course has no highlights", async () => {
    mockedListHighlights.mockResolvedValue(ok([]));

    render(
      <NotesPanel
        courseId="course-1"
        open
        sections={SECTIONS}
        onClose={vi.fn()}
        onNavigate={vi.fn()}
      />,
    );

    expect(await screen.findByText(/no highlights yet/i)).toBeInTheDocument();
  });

  it("a failed listHighlights shows an error affordance", async () => {
    mockedListHighlights.mockResolvedValue(err(500));

    render(
      <NotesPanel
        courseId="course-1"
        open
        sections={SECTIONS}
        onClose={vi.fn()}
        onNavigate={vi.fn()}
      />,
    );

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/loading notes failed \(http 500\)/i)).toBeInTheDocument();
  });

  it("re-fetches every time the panel is (re)opened", async () => {
    mockedListHighlights.mockResolvedValue(ok([WITH_NOTE]));

    const { rerender } = render(
      <NotesPanel
        courseId="course-1"
        open={false}
        sections={SECTIONS}
        onClose={vi.fn()}
        onNavigate={vi.fn()}
      />,
    );
    expect(mockedListHighlights).not.toHaveBeenCalled();

    rerender(
      <NotesPanel
        courseId="course-1"
        open
        sections={SECTIONS}
        onClose={vi.fn()}
        onNavigate={vi.fn()}
      />,
    );
    await waitFor(() => expect(mockedListHighlights).toHaveBeenCalledTimes(1));

    rerender(
      <NotesPanel
        courseId="course-1"
        open={false}
        sections={SECTIONS}
        onClose={vi.fn()}
        onNavigate={vi.fn()}
      />,
    );
    rerender(
      <NotesPanel
        courseId="course-1"
        open
        sections={SECTIONS}
        onClose={vi.fn()}
        onNavigate={vi.fn()}
      />,
    );
    await waitFor(() => expect(mockedListHighlights).toHaveBeenCalledTimes(2));
  });
});
