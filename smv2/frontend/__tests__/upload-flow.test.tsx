import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import UploadFlow from "@/components/upload/UploadFlow";
import {
  createCourse,
  editOutline,
  getJob,
  listSections,
  startIngest,
  uploadAsset,
  type CourseOut,
  type JobOut,
  type SectionOut,
} from "@/lib/api/client";

import { FakeEventSource } from "./support/fake-event-source";

const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

vi.mock("@/lib/api/client", () => ({
  API_BASE: "http://localhost:8000",
  TERMINAL_JOB_STATUSES: new Set(["succeeded", "failed"]),
  createCourse: vi.fn(),
  uploadAsset: vi.fn(),
  startIngest: vi.fn(),
  listSections: vi.fn(),
  editOutline: vi.fn(),
  getJob: vi.fn(),
}));

const mockedCreateCourse = vi.mocked(createCourse);
const mockedUploadAsset = vi.mocked(uploadAsset);
const mockedStartIngest = vi.mocked(startIngest);
const mockedListSections = vi.mocked(listSections);
const mockedEditOutline = vi.mocked(editOutline);
const mockedGetJob = vi.mocked(getJob);

function makeCourse(overrides: Partial<CourseOut> = {}): CourseOut {
  return {
    id: "course-1",
    title: "Book One",
    status: "draft",
    section_count: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeSection(overrides: Partial<SectionOut> = {}): SectionOut {
  return {
    id: "sec-1",
    title: "Chapter One",
    order_index: 0,
    page_start: 1,
    page_end: 10,
    lesson_status: "not_started",
    has_content: true,
    word_count: 100,
    ...overrides,
  };
}

function makeJob(overrides: Partial<JobOut> = {}): JobOut {
  return {
    id: "job-1",
    type: "ingest",
    status: "queued",
    payload: { course_id: "course-1" },
    result: null,
    progress: null,
    error: null,
    attempts: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function pdfFile(name: string): File {
  return new File(["%PDF-1.4 fake"], name, { type: "application/pdf" });
}

function makeAsset(filename: string) {
  return {
    id: `asset-${filename}`,
    course_id: "course-1",
    filename,
    content_type: "application/pdf",
    size_bytes: 1024,
    sha256: "abc",
    page_count: 10,
    status: "uploaded",
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

describe("UploadFlow", () => {
  let originalEventSource: typeof EventSource;

  beforeEach(() => {
    originalEventSource = globalThis.EventSource;
    FakeEventSource.instances = [];
    globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;

    mockedCreateCourse.mockResolvedValue({ status: 201, ok: true, data: makeCourse() });
    mockedUploadAsset.mockImplementation((_courseId, file: File) =>
      Promise.resolve({ status: 201, ok: true, data: makeAsset(file.name) }),
    );
    mockedStartIngest.mockResolvedValue({ status: 202, ok: true, data: { job_id: "job-1" } });
    mockedListSections.mockResolvedValue({ status: 200, ok: true, data: [makeSection()] });
    mockedEditOutline.mockResolvedValue({ status: 200, ok: true, data: [makeSection()] });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.useRealTimers();
    globalThis.EventSource = originalEventSource;
  });

  it("defaults the course title from the first filename and lets it be edited", () => {
    render(<UploadFlow files={[pdfFile("intro_to_testing.pdf")]} onClose={vi.fn()} />);

    const input = screen.getByRole("textbox") as HTMLInputElement;
    expect(input.value).toBe("intro to testing");
  });

  it("shows a per-file failure badge without blocking the rest of the upload", async () => {
    const user = userEvent.setup();
    mockedUploadAsset.mockImplementation((_courseId, file: File) => {
      if (file.name === "bad.pdf") {
        return Promise.resolve({ status: 500, ok: false });
      }
      return Promise.resolve({ status: 201, ok: true, data: makeAsset(file.name) });
    });

    render(<UploadFlow files={[pdfFile("good.pdf"), pdfFile("bad.pdf")]} onClose={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /create.*upload/i }));

    await screen.findByText("good.pdf");
    await waitFor(() => expect(screen.getByText(/uploaded/i)).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText(/failed/i)).toBeInTheDocument());

    // Ingest still starts even though one file failed.
    await waitFor(() => expect(mockedStartIngest).toHaveBeenCalledWith("course-1"));
  });

  it("shows live SSE stage/pct/message once the ingest job starts, never a bare spinner", async () => {
    const user = userEvent.setup();
    render(<UploadFlow files={[pdfFile("book.pdf")]} onClose={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /create.*upload/i }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    expect(screen.getByText(/preparing/i)).toBeInTheDocument();

    const source = FakeEventSource.instances[0];
    act(() => {
      source.emit("update", {
        id: "job-1",
        status: "running",
        progress: { stage: "outlining", pct: 20, message: "detecting outline for book.pdf" },
      });
    });

    expect(screen.getByText(/outlining/)).toBeInTheDocument();
    expect(screen.getByText(/20%/)).toBeInTheDocument();
    expect(screen.getByText(/detecting outline for book.pdf/)).toBeInTheDocument();
  });

  it("shows the stalled message after 120s with no SSE event, without treating it as a failure", async () => {
    // Fake timers from the start, so the stall setTimeout armed inside
    // useJobEvents' effect is itself a fake timer advanceTimersByTime can
    // reach. fireEvent.click (not userEvent) sidesteps userEvent's own
    // internal real-timer-dependent interaction delays entirely.
    vi.useFakeTimers();

    render(<UploadFlow files={[pdfFile("book.pdf")]} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /create.*upload/i }));

    // Drain the mocked createCourse -> uploadAsset -> startIngest chain
    // (native Promises, unaffected by fake timers) so the SSE connection
    // opens and its stall timer gets armed.
    await act(async () => {
      for (let i = 0; i < 10; i++) {
        await Promise.resolve();
      }
    });

    expect(FakeEventSource.instances).toHaveLength(1);

    act(() => {
      vi.advanceTimersByTime(120_000);
    });

    expect(screen.getByText(/still working/i)).toBeInTheDocument();
  });

  it("shows the ingest error with a retry that restarts the flow", async () => {
    const user = userEvent.setup();
    render(<UploadFlow files={[pdfFile("book.pdf")]} onClose={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /create.*upload/i }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    mockedGetJob.mockResolvedValue({
      status: 200,
      ok: true,
      data: makeJob({ status: "failed", error: "course has no assets to ingest" }),
    });

    act(() => {
      FakeEventSource.instances[0].emit("update", {
        id: "job-1",
        status: "failed",
        progress: null,
      });
    });

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/course has no assets to ingest/i);

    mockedStartIngest.mockClear();
    await user.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(mockedStartIngest).toHaveBeenCalledWith("course-1"));
  });

  it("goes straight to the reader on accept with no edits (no PATCH issued)", async () => {
    const user = userEvent.setup();
    render(<UploadFlow files={[pdfFile("book.pdf")]} onClose={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /create.*upload/i }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      FakeEventSource.instances[0].emit("update", {
        id: "job-1",
        status: "succeeded",
        progress: { stage: "done", pct: 100, message: "ingest complete" },
      });
    });

    await screen.findByRole("button", { name: /accept outline/i });
    await user.click(screen.getByRole("button", { name: /accept outline/i }));

    expect(mockedEditOutline).not.toHaveBeenCalled();
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/course/course-1"));
  });

  it("applies staged outline edits via one PATCH before navigating to the reader", async () => {
    const user = userEvent.setup();
    mockedListSections.mockResolvedValue({
      status: 200,
      ok: true,
      data: [makeSection({ id: "sec-1", title: "Chapter One" })],
    });

    render(<UploadFlow files={[pdfFile("book.pdf")]} onClose={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /create.*upload/i }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      FakeEventSource.instances[0].emit("update", {
        id: "job-1",
        status: "succeeded",
        progress: { stage: "done", pct: 100, message: "ingest complete" },
      });
    });

    await user.click(await screen.findByRole("button", { name: "Chapter One" }));
    const input = screen.getByRole("textbox", { name: /rename chapter one/i });
    await user.clear(input);
    await user.type(input, "Renamed Chapter{Enter}");

    await user.click(screen.getByRole("button", { name: /accept outline/i }));

    await waitFor(() =>
      expect(mockedEditOutline).toHaveBeenCalledWith("course-1", [
        { type: "rename", section_id: "sec-1", title: "Renamed Chapter" },
      ]),
    );
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/course/course-1"));
  });
});
