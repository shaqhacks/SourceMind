import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Home from "@/app/page";
import {
  createCourse,
  createJob,
  deleteCourse,
  getHealth,
  getJob,
  listCourses,
  listJobs,
  type CourseOut,
  type JobOut,
} from "@/lib/api/client";

import { FakeEventSource } from "./support/fake-event-source";

vi.mock("@/lib/api/client", () => ({
  API_BASE: "http://localhost:8000",
  getHealth: vi.fn(),
  listJobs: vi.fn(),
  createJob: vi.fn(),
  getJob: vi.fn(),
  listCourses: vi.fn(),
  createCourse: vi.fn(),
  deleteCourse: vi.fn(),
}));

const mockedGetHealth = vi.mocked(getHealth);
const mockedListJobs = vi.mocked(listJobs);
const mockedCreateJob = vi.mocked(createJob);
const mockedGetJob = vi.mocked(getJob);
const mockedListCourses = vi.mocked(listCourses);
const mockedCreateCourse = vi.mocked(createCourse);
const mockedDeleteCourse = vi.mocked(deleteCourse);

function makeJob(overrides: Partial<JobOut> = {}): JobOut {
  return {
    id: "job-1",
    type: "noop",
    status: "queued",
    payload: null,
    result: null,
    progress: null,
    error: null,
    attempts: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeCourse(overrides: Partial<CourseOut> = {}): CourseOut {
  return {
    id: "course-1",
    title: "Intro to Testing",
    status: "draft",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

let originalEventSource: typeof EventSource;

describe("Home page", () => {
  beforeEach(() => {
    originalEventSource = globalThis.EventSource;
    FakeEventSource.instances = [];
    globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;

    mockedGetHealth.mockResolvedValue({ data: { status: "ok", version: "0.1.0" }, status: 200, ok: true });
    mockedListJobs.mockResolvedValue({ data: [], status: 200, ok: true });
    mockedListCourses.mockResolvedValue({ data: [], status: 200, ok: true });
  });

  afterEach(() => {
    globalThis.EventSource = originalEventSource;
    vi.clearAllMocks();
  });

  it("shows the API ok state once the health check resolves", async () => {
    render(<Home />);

    const status = await screen.findByTestId("health-ok");
    expect(status).toHaveTextContent("API: ok");
    expect(status).toHaveTextContent("v0.1.0");
  });

  it("shows a retryable error banner when the health check fails", async () => {
    mockedGetHealth.mockResolvedValue({ error: new Error("boom"), ok: false });
    render(<Home />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/could not reach the api/i);
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("creates a job and reflects live SSE status/progress updates, refreshing the list on completion", async () => {
    const queuedJob = makeJob({ status: "queued" });
    mockedCreateJob.mockResolvedValue({ data: queuedJob, status: 202, ok: true });

    const user = userEvent.setup();
    render(<Home />);
    await screen.findByTestId("health-ok");

    await user.click(screen.getByRole("button", { name: /run no-op job/i }));
    await waitFor(() => expect(mockedCreateJob).toHaveBeenCalledWith({ type: "noop" }));
    expect(screen.getByTestId("current-job")).toHaveTextContent("queued");

    const source = FakeEventSource.instances[0];
    expect(source.url).toContain("/api/jobs/job-1/events");

    act(() => {
      source.emit("update", {
        id: "job-1",
        status: "running",
        progress: { stage: "working", pct: 50, message: "halfway there" },
      });
    });
    expect(screen.getByTestId("current-job")).toHaveTextContent("running");
    expect(screen.getByTestId("current-job")).toHaveTextContent("working");
    expect(screen.getByTestId("current-job")).toHaveTextContent("halfway there");

    const succeededJob = makeJob({ status: "succeeded" });
    mockedListJobs.mockResolvedValue({ data: [succeededJob], status: 200, ok: true });

    act(() => {
      source.emit("update", { id: "job-1", status: "succeeded", progress: null });
    });

    expect(screen.getByTestId("current-job")).toHaveTextContent("succeeded");
    expect(source.closed).toBe(true);
    // Mount + right after createJob (shows "queued" immediately) + the
    // terminal-event refresh.
    await waitFor(() => expect(mockedListJobs).toHaveBeenCalledTimes(3));
  });

  it("falls back to a one-shot GET (not a reconnect) when the SSE stream errors", async () => {
    const queuedJob = makeJob({ status: "queued" });
    mockedCreateJob.mockResolvedValue({ data: queuedJob, status: 202, ok: true });
    const refreshedJob = makeJob({ status: "running" });
    mockedGetJob.mockResolvedValue({ data: refreshedJob, status: 200, ok: true });

    const user = userEvent.setup();
    render(<Home />);
    await screen.findByTestId("health-ok");
    await user.click(screen.getByRole("button", { name: /run no-op job/i }));
    await waitFor(() => expect(screen.getByTestId("current-job")).toHaveTextContent("queued"));

    const source = FakeEventSource.instances[0];
    act(() => {
      source.emitError();
    });

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/lost connection to the job stream/i);

    await user.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => expect(mockedGetJob).toHaveBeenCalledWith("job-1"));
    await waitFor(() => expect(screen.getByTestId("current-job")).toHaveTextContent("running"));
    // No reconnect attempt — still the one EventSource from job creation.
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("creates a course through the form and lists it", async () => {
    const course = makeCourse({ title: "New Course" });
    mockedCreateCourse.mockResolvedValue({ data: course, status: 201, ok: true });

    const user = userEvent.setup();
    render(<Home />);
    await screen.findByTestId("health-ok");

    mockedListCourses.mockResolvedValue({ data: [course], status: 200, ok: true });

    await user.type(screen.getByLabelText(/course title/i), "New Course");
    await user.click(screen.getByRole("button", { name: /create course/i }));

    await waitFor(() => expect(mockedCreateCourse).toHaveBeenCalledWith({ title: "New Course" }));
    expect(await screen.findByText("New Course")).toBeInTheDocument();
  });

  it("deletes a course and removes it from the list", async () => {
    const course = makeCourse();
    mockedListCourses.mockResolvedValueOnce({ data: [course], status: 200, ok: true });
    mockedDeleteCourse.mockResolvedValue({ status: 204, ok: true });

    const user = userEvent.setup();
    render(<Home />);
    await screen.findByText(course.title);

    mockedListCourses.mockResolvedValue({ data: [], status: 200, ok: true });
    await user.click(screen.getByRole("button", { name: /delete/i }));

    await waitFor(() => expect(mockedDeleteCourse).toHaveBeenCalledWith(course.id));
    await waitFor(() => expect(screen.queryByText(course.title)).not.toBeInTheDocument());
  });

  it("shows a non-retryable error banner when course creation is rejected", async () => {
    mockedCreateCourse.mockResolvedValue({ error: new Error("bad title"), status: 422, ok: false });

    const user = userEvent.setup();
    render(<Home />);
    await screen.findByTestId("health-ok");

    await user.type(screen.getByLabelText(/course title/i), "x");
    await user.click(screen.getByRole("button", { name: /create course/i }));

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/creating course failed/i);
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });
});
