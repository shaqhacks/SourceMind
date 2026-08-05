import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

import { err, ok } from "./support/api-result";
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
  getJob: vi.fn(),
  listSections: vi.fn(),
  editOutline: vi.fn(),
}));

const mockedCreateCourse = vi.mocked(createCourse);
const mockedUploadAsset = vi.mocked(uploadAsset);
const mockedStartIngest = vi.mocked(startIngest);
const mockedGetJob = vi.mocked(getJob);
const mockedListSections = vi.mocked(listSections);
const mockedEditOutline = vi.mocked(editOutline);

function makeCourse(overrides: Partial<CourseOut> = {}): CourseOut {
  return {
    id: "course-1",
    title: "Book One",
    status: "draft",
    section_count: 0,
    failed_asset_count: 0,
    is_sample: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
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
    error_detail: null,
    retryable: true,
    attempts: 0,
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
    lesson_status: "none",
    has_content: true,
    word_count: 100,
    kind: "content",
    chapter_label: null,
    asset_id: null,
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
    html_status: "none" as const,
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

/** Drives a fresh render through course creation, upload, and a succeeded
 * ingest job, landing on the "confirming-outline" step. */
async function renderThroughIngestSuccess(files: File[] = [pdfFile("book.pdf")]) {
  const user = userEvent.setup();
  render(<UploadFlow files={files} onClose={vi.fn()} />);

  await user.click(screen.getByRole("button", { name: /create.*upload/i }));
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

  act(() => {
    FakeEventSource.instances[0].emit("update", {
      id: "job-1",
      status: "succeeded",
      progress: { stage: "done", pct: 100, message: "ingest complete" },
    });
  });

  await screen.findByText(/detected outline/i);
  return user;
}

describe("UploadFlow", () => {
  let originalEventSource: typeof EventSource;

  beforeEach(() => {
    originalEventSource = globalThis.EventSource;
    FakeEventSource.instances = [];
    globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;

    mockedCreateCourse.mockResolvedValue(ok(makeCourse(), 201));
    mockedUploadAsset.mockImplementation((_courseId, file: File) =>
      Promise.resolve(ok(makeAsset(file.name), 201)),
    );
    mockedStartIngest.mockResolvedValue(ok({ job_id: "job-1" }, 202));
    mockedListSections.mockResolvedValue(ok([makeSection()]));
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
        return Promise.resolve(err(500));
      }
      return Promise.resolve(ok(makeAsset(file.name), 201));
    });

    render(<UploadFlow files={[pdfFile("good.pdf"), pdfFile("bad.pdf")]} onClose={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /create.*upload/i }));

    await screen.findByText("good.pdf");
    await waitFor(() => expect(screen.getByText(/uploaded/i)).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText(/failed/i)).toBeInTheDocument());

    // Ingest still starts even though one file failed.
    await waitFor(() => expect(mockedStartIngest).toHaveBeenCalledWith("course-1"));
  });

  it("shows the uploaded page count once known", async () => {
    const user = userEvent.setup();
    mockedUploadAsset.mockResolvedValue(ok(makeAsset("book.pdf"), 201));

    render(<UploadFlow files={[pdfFile("book.pdf")]} onClose={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /create.*upload/i }));

    await waitFor(() => expect(screen.getByText(/uploaded.*10 pages/i)).toBeInTheDocument());
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

  it("advances the step indicator Upload -> Confirm outline, marking completed steps with a checkmark", async () => {
    // Hold the upload open so the "uploading" phase is observable instead of
    // resolving synchronously through to ingest.
    let resolveUpload!: (result: Awaited<ReturnType<typeof uploadAsset>>) => void;
    mockedUploadAsset.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveUpload = resolve;
        }),
    );

    render(<UploadFlow files={[pdfFile("book.pdf")]} onClose={vi.fn()} />);

    function stepCircle(label: "Upload" | "Confirm outline" | "Start reading"): HTMLElement {
      const indicator = screen.getByRole("list", { name: /upload progress/i });
      const circle = within(indicator).getByText(label).previousElementSibling;
      if (!(circle instanceof HTMLElement)) throw new Error(`no step circle for "${label}"`);
      return circle;
    }

    // Naming/uploading phase: Upload is the current step.
    expect(stepCircle("Upload")).toHaveAttribute("aria-current", "step");
    expect(stepCircle("Upload")).toHaveTextContent("1");
    expect(stepCircle("Confirm outline")).not.toHaveAttribute("aria-current");
    expect(stepCircle("Confirm outline")).toHaveTextContent("2");

    fireEvent.click(screen.getByRole("button", { name: /create.*upload/i }));
    await waitFor(() => expect(mockedCreateCourse).toHaveBeenCalled());

    // Finish the upload, ingest, and let the job succeed.
    await act(async () => {
      resolveUpload(ok(makeAsset("book.pdf"), 201));
    });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() => {
      FakeEventSource.instances[0].emit("update", {
        id: "job-1",
        status: "succeeded",
        progress: { stage: "done", pct: 100, message: "ingest complete" },
      });
    });

    await waitFor(() => expect(stepCircle("Confirm outline")).toHaveAttribute("aria-current", "step"));
    expect(stepCircle("Upload")).not.toHaveAttribute("aria-current");
    expect(stepCircle("Upload")).toHaveTextContent("✓");
  });

  it("fetches and shows the detected outline for confirmation once ingest succeeds, without navigating yet", async () => {
    mockedListSections.mockResolvedValue(ok([makeSection({ title: "Chapter One" })]));

    await renderThroughIngestSuccess();

    expect(mockedListSections).toHaveBeenCalledWith("course-1");
    expect(screen.getByText("Chapter One")).toBeInTheDocument();
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("shows a retryable error if fetching the detected outline fails", async () => {
    mockedListSections.mockResolvedValueOnce(err(500));
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

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/loading the detected outline/i);

    mockedListSections.mockResolvedValueOnce(ok([makeSection({ title: "Chapter One" })]));
    await user.click(screen.getByRole("button", { name: /retry/i }));

    await screen.findByText("Chapter One");
  });

  it("accepting the outline with no edits navigates straight to the reader, with no PATCH", async () => {
    const user = await renderThroughIngestSuccess();

    await user.click(screen.getByRole("button", { name: /accept outline.*start reading/i }));

    expect(mockedEditOutline).not.toHaveBeenCalled();
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/course/course-1"));
  });

  it("accepting the outline with staged edits issues one edit_outline PATCH before navigating", async () => {
    mockedListSections.mockResolvedValue(ok([makeSection({ id: "sec-1", title: "Chapter One" })]));
    mockedEditOutline.mockResolvedValue(ok([makeSection({ id: "sec-1", title: "Renamed" })]));
    const user = await renderThroughIngestSuccess();

    await user.click(screen.getByRole("button", { name: "Chapter One" }));
    const input = screen.getByRole("textbox", { name: /rename chapter one/i });
    await user.clear(input);
    await user.type(input, "Renamed{Enter}");

    await user.click(screen.getByRole("button", { name: /accept outline.*start reading/i }));

    await waitFor(() =>
      expect(mockedEditOutline).toHaveBeenCalledWith("course-1", [
        { type: "rename", section_id: "sec-1", title: "Renamed" },
      ]),
    );
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/course/course-1"));
  });

  it("shows a retryable error and keeps the staged draft if applying the outline fails", async () => {
    mockedListSections.mockResolvedValue(ok([makeSection({ id: "sec-1", title: "Chapter One" })]));
    mockedEditOutline.mockResolvedValue(err(500));
    const user = await renderThroughIngestSuccess();

    await user.click(screen.getByRole("button", { name: "Chapter One" }));
    const input = screen.getByRole("textbox", { name: /rename chapter one/i });
    await user.clear(input);
    await user.type(input, "Renamed{Enter}");
    await user.click(screen.getByRole("button", { name: /accept outline.*start reading/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/applying your outline edits failed/i);
    expect(mockPush).not.toHaveBeenCalled();
    // The staged draft survived the failed attempt.
    expect(screen.getByRole("button", { name: "Renamed" })).toBeInTheDocument();
  });

  it("Cancel on the outline step closes the dialog via onClose, without navigating", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<UploadFlow files={[pdfFile("book.pdf")]} onClose={onClose} />);

    await user.click(screen.getByRole("button", { name: /create.*upload/i }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() => {
      FakeEventSource.instances[0].emit("update", {
        id: "job-1",
        status: "succeeded",
        progress: { stage: "done", pct: 100, message: "ingest complete" },
      });
    });

    await user.click(await screen.findByRole("button", { name: /^cancel$/i }));

    expect(onClose).toHaveBeenCalled();
    expect(mockPush).not.toHaveBeenCalled();
  });
});
