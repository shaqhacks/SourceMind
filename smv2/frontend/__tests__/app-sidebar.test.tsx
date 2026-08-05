import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AppSidebar from "@/components/AppSidebar";
import { getReviewSummary, listCourses } from "@/lib/api/client";

let mockPathname = "/";

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
}));

vi.mock("@/lib/hooks/useSidebarCollapsed", () => ({
  useSidebarCollapsed: () => ({ collapsed: false }),
}));

vi.mock("@/components/upload/UploadFlow", () => ({
  default: ({ files }: { files: File[] }) => (
    <div role="dialog" aria-label="Start a new course">
      {files.map((file) => (
        <span key={file.name}>{file.name}</span>
      ))}
    </div>
  ),
}));

vi.mock("@/lib/api/client", () => ({
  listCourses: vi.fn().mockResolvedValue({ status: 200, ok: true, data: [] }),
  getReviewSummary: vi.fn().mockResolvedValue({ status: 200, ok: true, data: { due_total: 0, courses: [] } }),
  getLlmUsage: vi.fn().mockResolvedValue({ status: 200, ok: true, data: { calls: 0, input_tokens: 0, output_tokens: 0, est_cost_usd: 0 } }),
}));

const mockedListCourses = vi.mocked(listCourses);
const mockedGetReviewSummary = vi.mocked(getReviewSummary);

describe("AppSidebar", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    mockPathname = "/";
    delete process.env.NEXT_PUBLIC_SMV2_AI_READINESS_UI;
  });

  it("shows Jobs and Settings as top-level navigation links", () => {
    render(<AppSidebar />);

    expect(screen.getByRole("link", { name: "Jobs" })).toHaveAttribute("href", "/jobs");
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
  });

  it("keeps Jobs and Settings visible when credential editing is flag-disabled", () => {
    process.env.NEXT_PUBLIC_SMV2_AI_READINESS_UI = "0";

    render(<AppSidebar />);

    expect(screen.getByRole("link", { name: "Jobs" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
  });

  it("marks Settings current on the settings route", () => {
    mockPathname = "/settings";

    render(<AppSidebar />);

    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
  });

  it("shows flashcards and per-course badges from canonical overdue counts only", async () => {
    mockedListCourses.mockResolvedValue({
      status: 200,
      ok: true,
      data: [
        {
          id: "course-1",
          title: "Course One",
          status: "ready",
          section_count: 3,
          failed_asset_count: 0,
          is_sample: false,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
          progress: null,
        },
      ],
    });
    mockedGetReviewSummary.mockResolvedValue({
      status: 200,
      ok: true,
      data: {
        due_total: 0,
        daily_throughput: 0,
        backlog_warning: false,
        courses: [
          {
            course_id: "course-1",
            title: "Course One",
            due_count: 0,
            overdue_count: 4,
            new_count: 6,
            available_count: 10,
            total_count: 10,
          },
        ],
      },
    });

    render(<AppSidebar />);

    const flashcardsLink = await screen.findByRole("link", { name: /flashcards/i });
    expect(flashcardsLink).toHaveAttribute("href", "/flashcards");
    expect(within(flashcardsLink).getByText("4")).toBeInTheDocument();
    expect(await screen.findByText(/3 sections · 4 due/i)).toBeInTheDocument();
  });

  it("uses the shared picker contract for supported Markdown files", () => {
    render(<AppSidebar />);

    const input = screen.getByLabelText("Upload course files");
    expect(input).toHaveAttribute(
      "accept",
      ".pdf,.md,.markdown,.txt,.text,.html,.htm,application/pdf,text/markdown,text/plain,text/html",
    );

    fireEvent.change(input, {
      target: { files: [new File(["# Intro"], "intro.md", { type: "text/markdown" })] },
    });

    expect(screen.getByRole("dialog", { name: /start a new course/i })).toHaveTextContent(
      "intro.md",
    );
  });

  it("keeps blocked archive drops visible with actionable feedback instead of silently ignoring them", () => {
    render(<AppSidebar />);

    const dropZone = screen.getByText(/drop files here/i);
    fireEvent.drop(dropZone, {
      dataTransfer: {
        files: [
          new File(["PK"], "deck.pptx", {
            type: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
          }),
        ],
      },
    });

    expect(screen.getByRole("status")).toHaveTextContent(/deck\.pptx/i);
    expect(screen.getByRole("status")).toHaveTextContent(/not supported yet/i);
  });
});
