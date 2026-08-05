import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CourseCard from "@/components/dashboard/CourseCard";
import {
  deleteCourse,
  findActiveIngestJob,
  findLatestIngestJob,
  listAssets,
  startIngest,
  type AssetOut,
  type CourseOut,
  type JobOut,
} from "@/lib/api/client";

import { ok } from "./support/api-result";
import { FakeEventSource } from "./support/fake-event-source";

vi.mock("@/lib/api/client", () => ({
  API_BASE: "http://localhost:8000",
  TERMINAL_JOB_STATUSES: new Set(["succeeded", "failed"]),
  deleteCourse: vi.fn(),
  exportCourseUrl: (courseId: string) => `http://localhost:8000/api/courses/${courseId}/export`,
  findActiveIngestJob: vi.fn(),
  findLatestIngestJob: vi.fn(),
  listAssets: vi.fn(),
  startIngest: vi.fn(),
}));

const mockedDeleteCourse = vi.mocked(deleteCourse);
const mockedFindActiveIngestJob = vi.mocked(findActiveIngestJob);
const mockedFindLatestIngestJob = vi.mocked(findLatestIngestJob);
const mockedListAssets = vi.mocked(listAssets);
const mockedStartIngest = vi.mocked(startIngest);

function makeAsset(overrides: Partial<AssetOut> = {}): AssetOut {
  return {
    id: "asset-1",
    course_id: "course-1",
    filename: "book.pdf",
    content_type: "application/pdf",
    size_bytes: 1024,
    sha256: "abc",
    html_status: "none",
    page_count: 10,
    status: "stored",
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeCourse(overrides: Partial<CourseOut> = {}): CourseOut {
  return {
    id: "course-1",
    title: "Distributed Systems",
    status: "ready",
    section_count: 4,
    failed_asset_count: 0,
    is_sample: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    progress: null,
    ...overrides,
  };
}

function makeJob(overrides: Partial<JobOut> = {}): JobOut {
  return {
    id: "job-1",
    type: "ingest",
    status: "running",
    payload: { course_id: "course-1" },
    result: null,
    progress: null,
    error: null,
    error_detail: null,
    retryable: true,
    attempts: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("CourseCard", () => {
  let originalEventSource: typeof EventSource;

  beforeEach(() => {
    originalEventSource = globalThis.EventSource;
    FakeEventSource.instances = [];
    globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;

    mockedDeleteCourse.mockResolvedValue(ok(undefined));
    mockedFindActiveIngestJob.mockResolvedValue(null);
    mockedFindLatestIngestJob.mockResolvedValue(null);
    mockedListAssets.mockResolvedValue(ok([]));
    mockedStartIngest.mockResolvedValue(ok({ job_id: "job-2" }, 202));
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    globalThis.EventSource = originalEventSource;
  });

  it("shows a Ready badge and an export link for a ready course", () => {
    render(<CourseCard course={makeCourse({ status: "ready" })} onDeleted={vi.fn()} onNeedsRefresh={vi.fn()} />);

    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /export/i })).toHaveAttribute(
      "href",
      "http://localhost:8000/api/courses/course-1/export",
    );
  });

  it("shows a Draft badge and no export link for a draft course", () => {
    render(<CourseCard course={makeCourse({ status: "draft" })} onDeleted={vi.fn()} onNeedsRefresh={vi.fn()} />);

    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /export/i })).not.toBeInTheDocument();
  });

  it("rediscovers the active ingest job and shows live SSE stage/pct for an ingesting course", async () => {
    mockedFindActiveIngestJob.mockResolvedValue(makeJob({ id: "job-1" }));

    render(<CourseCard course={makeCourse({ status: "ingesting" })} onDeleted={vi.fn()} onNeedsRefresh={vi.fn()} />);

    expect(screen.getByText(/preparing/i)).toBeInTheDocument();
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      FakeEventSource.instances[0].emit("update", {
        id: "job-1",
        status: "running",
        progress: { stage: "writing sections", pct: 60, message: "writing Chapter 2" },
      });
    });

    expect(screen.getByText(/writing sections/)).toBeInTheDocument();
    expect(screen.getByText(/60%/)).toBeInTheDocument();
  });

  it("falls back to the failed job's error when no asset shows extract_failed", async () => {
    mockedFindLatestIngestJob.mockResolvedValue(
      makeJob({ id: "job-1", status: "failed", error: "course has no assets to ingest" }),
    );
    const onNeedsRefresh = vi.fn();
    const user = userEvent.setup();

    render(
      <CourseCard
        course={makeCourse({ status: "ingest_failed" })}
        onDeleted={vi.fn()}
        onNeedsRefresh={onNeedsRefresh}
      />,
    );

    expect(await screen.findByText(/course has no assets to ingest/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /retry ingest/i }));

    expect(mockedStartIngest).toHaveBeenCalledWith("course-1");
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      FakeEventSource.instances[0].emit("update", { id: "job-2", status: "succeeded", progress: null });
    });

    // A terminal status on the retried job means the course prop is now
    // stale (status should have flipped server-side) — the parent is
    // asked to refetch rather than the card guessing the new status.
    expect(onNeedsRefresh).toHaveBeenCalled();
  });

  it("shows a per-asset failure badge (filename + error) instead of the job error when one exists", async () => {
    mockedFindLatestIngestJob.mockResolvedValue(
      makeJob({ id: "job-1", status: "failed", error: "unhandled worker exception" }),
    );
    mockedListAssets.mockResolvedValue({
      status: 200,
      ok: true,
      data: [
        makeAsset({ id: "asset-1", filename: "chapter1.pdf", status: "stored" }),
        makeAsset({
          id: "asset-2",
          filename: "chapter2.pdf",
          status: "extract_failed",
          error: "password protected",
        }),
      ],
    });

    render(
      <CourseCard
        course={makeCourse({ status: "ingest_failed" })}
        onDeleted={vi.fn()}
        onNeedsRefresh={vi.fn()}
      />,
    );

    expect(await screen.findByText(/chapter2\.pdf/)).toHaveTextContent("password protected");
    // The job-level message and the non-failed asset are not shown once a
    // specific asset can be pinned as the cause.
    expect(screen.queryByText(/unhandled worker exception/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/chapter1\.pdf/)).not.toBeInTheDocument();
  });

  it("deletes only after an explicit confirm step", async () => {
    const onDeleted = vi.fn();
    const user = userEvent.setup();
    render(<CourseCard course={makeCourse()} onDeleted={onDeleted} onNeedsRefresh={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    expect(mockedDeleteCourse).not.toHaveBeenCalled();
    expect(screen.getByText(/delete this course/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /confirm/i }));

    expect(mockedDeleteCourse).toHaveBeenCalledWith("course-1");
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith("course-1"));
  });

  it("cancels the delete confirmation without deleting", async () => {
    const onDeleted = vi.fn();
    const user = userEvent.setup();
    render(<CourseCard course={makeCourse()} onDeleted={onDeleted} onNeedsRefresh={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(mockedDeleteCourse).not.toHaveBeenCalled();
    expect(screen.queryByText(/delete this course/i)).not.toBeInTheDocument();
    expect(onDeleted).not.toHaveBeenCalled();
  });

  it("a ready course with failed_asset_count > 0 shows a badge, and expanding it lazy-loads the per-asset detail", async () => {
    mockedListAssets.mockResolvedValue(
      ok([
        makeAsset({ id: "a1", filename: "chapter3.pdf", status: "extract_failed", error: "password protected" }),
      ]),
    );
    const user = userEvent.setup();
    render(
      <CourseCard
        course={makeCourse({ failed_asset_count: 1 })}
        onDeleted={vi.fn()}
        onNeedsRefresh={vi.fn()}
      />,
    );

    const badge = screen.getByRole("button", { name: /1 file failed extraction/i });
    expect(badge).toHaveAttribute("aria-expanded", "false");
    expect(mockedListAssets).not.toHaveBeenCalled();

    await user.click(badge);

    expect(badge).toHaveAttribute("aria-expanded", "true");
    expect(mockedListAssets).toHaveBeenCalledWith("course-1");
    expect(await screen.findByText(/chapter3\.pdf: password protected/i)).toBeInTheDocument();
  });

  it("does not show the failed-extraction badge when failed_asset_count is 0", () => {
    render(
      <CourseCard
        course={makeCourse({ failed_asset_count: 0 })}
        onDeleted={vi.fn()}
        onNeedsRefresh={vi.fn()}
      />,
    );

    expect(screen.queryByText(/failed extraction/i)).not.toBeInTheDocument();
  });

  it("shows the sample-course hint on the sample course card and persists dismissal", async () => {
    const user = userEvent.setup();

    const { unmount } = render(
      <CourseCard
        course={makeCourse({ is_sample: true })}
        onDeleted={vi.fn()}
        onNeedsRefresh={vi.fn()}
      />,
    );

    expect(screen.getByText(/this is a sample course — drop any pdf to create your own/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /dismiss hint/i }));
    expect(screen.queryByText(/this is a sample course/i)).not.toBeInTheDocument();
    unmount();

    render(
      <CourseCard
        course={makeCourse({ is_sample: true })}
        onDeleted={vi.fn()}
        onNeedsRefresh={vi.fn()}
      />,
    );

    expect(screen.queryByText(/this is a sample course/i)).not.toBeInTheDocument();
  });

  it("does not show the sample-course hint for a user-created course", () => {
    render(
      <CourseCard
        course={makeCourse({ is_sample: false })}
        onDeleted={vi.fn()}
        onNeedsRefresh={vi.fn()}
      />,
    );

    expect(screen.queryByText(/this is a sample course/i)).not.toBeInTheDocument();
  });
});
