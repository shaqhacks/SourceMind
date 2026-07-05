import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Home from "@/app/page";
import { createJob, getHealth, getJob, listJobs, type JobOut } from "@/lib/api/client";

vi.mock("@/lib/api/client", () => ({
  getHealth: vi.fn(),
  listJobs: vi.fn(),
  createJob: vi.fn(),
  getJob: vi.fn(),
}));

const mockedGetHealth = vi.mocked(getHealth);
const mockedListJobs = vi.mocked(listJobs);
const mockedCreateJob = vi.mocked(createJob);
const mockedGetJob = vi.mocked(getJob);

function makeJob(overrides: Partial<JobOut> = {}): JobOut {
  return {
    id: "job-1",
    type: "noop",
    status: "queued",
    payload: null,
    result: null,
    error: null,
    attempts: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("Home page", () => {
  beforeEach(() => {
    mockedGetHealth.mockResolvedValue({ data: { status: "ok", version: "0.1.0" }, status: 200 });
    mockedListJobs.mockResolvedValue({ data: [], status: 200 });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows the API ok state once the health check resolves", async () => {
    render(<Home />);

    const status = await screen.findByTestId("health-ok");
    expect(status).toHaveTextContent("API: ok");
    expect(status).toHaveTextContent("v0.1.0");
  });

  it("shows a retryable error banner when the health check fails", async () => {
    mockedGetHealth.mockResolvedValue({ error: new Error("boom") });
    render(<Home />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/could not reach the api/i);
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("creates a job, auto-refetches once ~600ms later, and reflects it in the jobs list", async () => {
    const queuedJob = makeJob({ status: "queued" });
    const succeededJob = makeJob({ status: "succeeded" });
    mockedCreateJob.mockResolvedValue({ data: queuedJob, status: 202 });
    mockedGetJob.mockResolvedValue({ data: succeededJob, status: 200 });
    mockedListJobs.mockResolvedValue({ data: [queuedJob], status: 200 });

    const user = userEvent.setup();
    render(<Home />);
    await screen.findByTestId("health-ok");

    await user.click(screen.getByRole("button", { name: /run no-op job/i }));

    await waitFor(() => expect(mockedCreateJob).toHaveBeenCalledWith({ type: "noop" }));
    expect(screen.getByTestId("current-job")).toHaveTextContent("queued");
    expect(screen.getAllByText("job-1").length).toBeGreaterThan(0);

    await waitFor(() => expect(mockedGetJob).toHaveBeenCalledWith("job-1"), { timeout: 1500 });
    await waitFor(() =>
      expect(screen.getByTestId("current-job")).toHaveTextContent("succeeded"),
    );
  });

  it("manually refreshes the current job via the Refresh button", async () => {
    const queuedJob = makeJob({ status: "queued" });
    const runningJob = makeJob({ status: "running" });
    mockedCreateJob.mockResolvedValue({ data: queuedJob, status: 202 });
    mockedGetJob.mockResolvedValue({ data: runningJob, status: 200 });
    mockedListJobs.mockResolvedValue({ data: [queuedJob], status: 200 });

    const user = userEvent.setup();
    render(<Home />);
    await screen.findByTestId("health-ok");

    await user.click(screen.getByRole("button", { name: /run no-op job/i }));
    await waitFor(() => expect(screen.getByTestId("current-job")).toHaveTextContent("queued"));

    await user.click(screen.getByRole("button", { name: /^refresh$/i }));
    await waitFor(() => expect(screen.getByTestId("current-job")).toHaveTextContent("running"));
  });
});
