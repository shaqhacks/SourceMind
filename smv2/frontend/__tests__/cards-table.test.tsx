import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CardsTable from "@/components/flashcards/CardsTable";
import type { ApiResult, CardOut, GradeCardOut, ReviewQueueCardOut } from "@/lib/api/client";
import { gradeCardAndNotify } from "@/lib/review/gradeCardAndNotify";

vi.mock("@/lib/review/gradeCardAndNotify", () => ({
  gradeCardAndNotify: vi.fn(),
}));

const mockGradeCardAndNotify = vi.mocked(gradeCardAndNotify);

function makeCard(overrides: Partial<CardOut> = {}): CardOut {
  return {
    id: "card-1",
    section_id: "sec-1",
    front_md: "What is ATP?",
    back_md: "ATP is the cell's energy currency.",
    position: 0,
    origin: "generated",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeQueueCard(overrides: Partial<ReviewQueueCardOut> = {}): ReviewQueueCardOut {
  return {
    id: "card-1",
    section_id: "sec-1",
    front_md: "What is ATP?",
    back_md: "ATP is the cell's energy currency.",
    due_at: "2026-01-01T00:00:00Z",
    is_new: false,
    interval_days: 1,
    ease: 2.5,
    reps: 1,
    chapter_label: "Cell Biology & Basics",
    section_title: "Energy",
    is_due: true,
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

function failedGradeResult(): ApiResult<GradeCardOut> {
  return { ok: false, status: 503 };
}

describe("CardsTable", () => {
  beforeEach(() => {
    mockGradeCardAndNotify.mockResolvedValue(successfulGradeResult());
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders cards as a stacked accessible list without table semantics", () => {
    render(
      <CardsTable
        chapterTitle="Cell Biology & Basics"
        cards={[
          makeCard(),
          makeCard({ id: "card-2", front_md: "Define ATP.", origin: "user" }),
        ]}
        dueCardsById={
          new Map([
            ["card-1", makeQueueCard()],
            [
              "card-2",
              makeQueueCard({
                id: "card-2",
                front_md: "Define ATP.",
                is_due: false,
                is_new: true,
                last_grade: 1,
              }),
            ],
          ])
        }
      />,
    );

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const list = screen.getByRole("list", { name: /all cards — cell biology & basics/i });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(within(list).getByText("Due now")).toBeInTheDocument();
    expect(within(list).getByText("New")).toBeInTheDocument();
    expect(within(list).getByText("Needs attention")).toBeInTheDocument();
    expect(within(list).getByText("User-added")).toBeInTheDocument();
  });

  it("reveals the answer and the four review grade controls on demand", async () => {
    const user = userEvent.setup();
    render(
      <CardsTable
        chapterTitle="Cell Biology & Basics"
        cards={[makeCard()]}
        dueCardsById={new Map([["card-1", makeQueueCard()]])}
      />,
    );

    const item = screen.getByText("What is ATP?").closest("li")!;
    expect(within(item).queryByText(/energy currency/i)).not.toBeInTheDocument();
    expect(within(item).queryByRole("group", { name: /grade flashcard/i })).not.toBeInTheDocument();

    await user.click(within(item).getByRole("button", { name: /show answer/i }));

    expect(within(item).getByText(/energy currency/i)).toBeInTheDocument();
    expect(within(item).getByRole("group", { name: /grade flashcard/i })).toBeInTheDocument();
    expect(within(item).getByRole("button", { name: /again/i })).toBeInTheDocument();
    expect(within(item).getByRole("button", { name: /hard/i })).toBeInTheDocument();
    expect(within(item).getByRole("button", { name: /good/i })).toBeInTheDocument();
    expect(within(item).getByRole("button", { name: /easy/i })).toBeInTheDocument();
  });

  it("keeps controls retryable after a failed grade and locks them after success", async () => {
    mockGradeCardAndNotify.mockResolvedValueOnce(failedGradeResult()).mockResolvedValueOnce(
      successfulGradeResult(),
    );
    const user = userEvent.setup();
    render(
      <CardsTable
        chapterTitle="Cell Biology & Basics"
        cards={[makeCard()]}
        dueCardsById={new Map([["card-1", makeQueueCard()]])}
      />,
    );

    const item = screen.getByText("What is ATP?").closest("li")!;
    await user.click(within(item).getByRole("button", { name: /show answer/i }));
    await user.click(within(item).getByRole("button", { name: /again/i }));

    expect(await within(item).findByRole("alert")).toHaveTextContent(/could not save/i);
    expect(within(item).getByRole("button", { name: /again/i })).toBeEnabled();

    await user.click(within(item).getByRole("button", { name: /good/i }));

    expect(await within(item).findByText("Saved as Good.")).toBeInTheDocument();
    await waitFor(() => {
      for (const button of within(item).getAllByRole("button", { name: /again|hard|good|easy/i })) {
        expect(button).toBeDisabled();
      }
    });
    expect(mockGradeCardAndNotify).toHaveBeenCalledTimes(2);
  });
});
