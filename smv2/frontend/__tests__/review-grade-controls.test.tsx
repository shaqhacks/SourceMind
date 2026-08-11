import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ReviewGradeControls from "@/components/review/ReviewGradeControls";
import { gradeCardAndNotify } from "@/lib/review/gradeCardAndNotify";
import type { ApiResult, GradeCardOut, ReviewQueueCardOut } from "@/lib/api/client";

vi.mock("@/lib/review/gradeCardAndNotify", () => ({
  gradeCardAndNotify: vi.fn(),
}));

const mockGradeCardAndNotify = vi.mocked(gradeCardAndNotify);
const onGraded = vi.fn();

function reviewCard(overrides: Partial<ReviewQueueCardOut> = {}): ReviewQueueCardOut {
  return {
    id: "card-1",
    section_id: "sec-1",
    front_md: "Front",
    back_md: "Back",
    due_at: null,
    is_new: true,
    interval_days: 1,
    ease: 2.5,
    reps: 0,
    chapter_label: "Chapter 1",
    section_title: "Section 1",
    is_due: false,
    last_grade: null,
    ...overrides,
  };
}

function successfulGradeResult(): ApiResult<GradeCardOut> {
  return {
    ok: true,
    status: 200,
    data: { next_due_at: "2026-08-10T00:00:00Z", remaining_due: 0 },
  };
}

function failedGradeResult(status = 503): ApiResult<GradeCardOut> {
  return { ok: false, status };
}

function deferredGradeResponse() {
  let resolve!: (value: ApiResult<GradeCardOut>) => void;
  const promise = new Promise<ApiResult<GradeCardOut>>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe("ReviewGradeControls", () => {
  beforeEach(() => {
    mockGradeCardAndNotify.mockResolvedValue(successfulGradeResult());
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("submits the selected grade once and disables every grade while pending", async () => {
    const request = deferredGradeResponse();
    mockGradeCardAndNotify.mockReturnValue(request.promise);
    const user = userEvent.setup();

    render(<ReviewGradeControls card={reviewCard()} onGraded={onGraded} />);
    await user.click(screen.getByRole("button", { name: /good/i }));

    expect(mockGradeCardAndNotify).toHaveBeenCalledTimes(1);
    expect(mockGradeCardAndNotify).toHaveBeenCalledWith("card-1", 3, expect.any(Number));
    for (const button of screen.getAllByRole("button")) {
      expect(button).toBeDisabled();
    }

    request.resolve(successfulGradeResult());
    await waitFor(() => expect(onGraded).toHaveBeenCalledWith(3, successfulGradeResult()));
  });

  it("keeps controls available and announces a failed grade", async () => {
    mockGradeCardAndNotify.mockResolvedValue(failedGradeResult(503));
    const user = userEvent.setup();

    render(<ReviewGradeControls card={reviewCard()} onGraded={onGraded} />);
    await user.click(screen.getByRole("button", { name: /again/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not save/i);
    expect(screen.getByRole("button", { name: /again/i })).toBeEnabled();
    expect(onGraded).not.toHaveBeenCalled();
  });

  it("renders existing interval previews for each grade", () => {
    render(<ReviewGradeControls card={reviewCard({ interval_days: 6, ease: 2.5, reps: 2 })} />);

    expect(screen.getByRole("button", { name: /again.*<10 min/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /hard.*7 days/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /good.*15 days/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /easy.*20 days/i })).toBeInTheDocument();
  });

  it("keeps the successful grade saved and locked after submission", async () => {
    const user = userEvent.setup();

    render(<ReviewGradeControls card={reviewCard()} onGraded={onGraded} />);
    await user.click(screen.getByRole("button", { name: /easy/i }));

    expect(await screen.findByText("Saved as Easy.")).toBeInTheDocument();
    for (const button of screen.getAllByRole("button")) {
      expect(button).toBeDisabled();
    }
  });

  it("exposes accessible grouped grade controls and alert state", async () => {
    mockGradeCardAndNotify.mockResolvedValue(failedGradeResult());
    const user = userEvent.setup();

    render(<ReviewGradeControls card={reviewCard()} />);

    expect(screen.getByRole("group", { name: /grade flashcard/i })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /hard/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not save/i);
  });

  it("does not submit another grade while the first request is pending", async () => {
    const request = deferredGradeResponse();
    mockGradeCardAndNotify.mockReturnValue(request.promise);
    const user = userEvent.setup();

    render(<ReviewGradeControls card={reviewCard()} onGraded={onGraded} />);
    await user.click(screen.getByRole("button", { name: /good/i }));
    await user.click(screen.getByRole("button", { name: /easy/i }));

    expect(mockGradeCardAndNotify).toHaveBeenCalledTimes(1);
  });

  it("does not submit duplicate grades from same-tick clicks before pending state renders", () => {
    const request = deferredGradeResponse();
    mockGradeCardAndNotify.mockReturnValue(request.promise);

    render(<ReviewGradeControls card={reviewCard()} onGraded={onGraded} />);
    const good = screen.getByRole("button", { name: /good/i });
    const easy = screen.getByRole("button", { name: /easy/i });

    good.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    easy.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    expect(mockGradeCardAndNotify).toHaveBeenCalledTimes(1);
    expect(mockGradeCardAndNotify).toHaveBeenCalledWith("card-1", 3, expect.any(Number));
  });
});
