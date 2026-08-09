import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CardsCTA from "@/components/reader/CardsCTA";
import SectionCards from "@/components/reader/SectionCards";
import {
  deleteCard,
  findActiveCardsJob,
  generateCards,
  getReviewQueue,
  getReviewSelection,
  listCards,
  patchCard,
  type ApiResult,
  type CardOut,
  type GradeCardOut,
  type ReviewQueueCardOut,
  type ReviewSelectionOut,
} from "@/lib/api/client";
import { notifyCardsSettled } from "@/lib/cards/cardsBus";
import { useKeyboardShortcuts } from "@/lib/hooks/useKeyboardShortcuts";
import { gradeCardAndNotify } from "@/lib/review/gradeCardAndNotify";
import { notifyReviewSettled } from "@/lib/review/reviewBus";

import { ok, err } from "./support/api-result";
import { FakeEventSource } from "./support/fake-event-source";

vi.mock("@/lib/api/client", () => ({
  API_BASE: "http://localhost:8000",
  TERMINAL_JOB_STATUSES: new Set(["succeeded", "failed"]),
  listCards: vi.fn(),
  generateCards: vi.fn(),
  findActiveCardsJob: vi.fn(),
  getJob: vi.fn(),
  patchCard: vi.fn(),
  deleteCard: vi.fn(),
  getReviewQueue: vi.fn(),
  getReviewSelection: vi.fn(),
}));

vi.mock("@/lib/review/gradeCardAndNotify", () => ({
  gradeCardAndNotify: vi.fn(),
}));

vi.mock("@/lib/review/reviewBus", () => ({
  notifyReviewSettled: vi.fn(),
}));

const mockedListCards = vi.mocked(listCards);
const mockedGenerateCards = vi.mocked(generateCards);
const mockedFindActiveCardsJob = vi.mocked(findActiveCardsJob);
const mockedPatchCard = vi.mocked(patchCard);
const mockedDeleteCard = vi.mocked(deleteCard);
const mockedGetReviewQueue = vi.mocked(getReviewQueue);
const mockedGetReviewSelection = vi.mocked(getReviewSelection);
const mockedGradeCardAndNotify = vi.mocked(gradeCardAndNotify);
const mockedNotifyReviewSettled = vi.mocked(notifyReviewSettled);

function makeCard(overrides: Partial<CardOut> = {}): CardOut {
  return {
    id: "card-1",
    section_id: "sec-1",
    front_md: "Front text",
    back_md: "Back text",
    position: 0,
    origin: "generated",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeReviewCard(overrides: Partial<ReviewQueueCardOut> = {}): ReviewQueueCardOut {
  return {
    id: "card-1",
    section_id: "sec-1",
    front_md: "Front text",
    back_md: "Back text",
    due_at: null,
    is_new: true,
    interval_days: 1,
    ease: 2.5,
    reps: 0,
    chapter_label: "Fractions",
    section_title: "Section 1",
    is_due: false,
    last_grade: null,
    ...overrides,
  };
}

function reviewQueue(cards: ReviewQueueCardOut[] = [makeReviewCard()]) {
  return ok({
    due: 0,
    new: cards.length,
    due_count: 0,
    new_count: cards.length,
    overdue_count: 0,
    available_count: cards.length,
    total: cards.length,
    total_count: cards.length,
    cards,
  });
}

function reviewSelection(cards: ReviewQueueCardOut[] = [makeReviewCard()]): ApiResult<ReviewSelectionOut> {
  return ok({
    cards,
    missing_card_ids: [],
  });
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

// A minimal stand-in for a reader-level shortcut (e.g. j/k chapter nav) —
// used to prove editing a card doesn't let it fire, without depending on
// the real reader shell's own shortcut wiring.
function ReaderShortcutProbe({ onJ }: { onJ: () => void }) {
  useKeyboardShortcuts({ j: onJ });
  return null;
}

describe("SectionCards", () => {
  beforeEach(() => {
    mockedFindActiveCardsJob.mockResolvedValue(null);
    mockedGetReviewQueue.mockResolvedValue(reviewQueue());
    mockedGetReviewSelection.mockResolvedValue(reviewSelection());
    mockedGradeCardAndNotify.mockResolvedValue(successfulGradeResult());
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders nothing when the section has no cards", async () => {
    mockedListCards.mockResolvedValue(ok([]));

    const { container } = render(
      <SectionCards courseId="course-1" chapterLabel="Fractions" sectionId="sec-1" />,
    );

    await waitFor(() => expect(mockedListCards).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("shows each card's front always, and reveals the back independently per card", async () => {
    mockedListCards.mockResolvedValue(
      ok([
        makeCard({ id: "c1", front_md: "Q1", back_md: "A1" }),
        makeCard({ id: "c2", front_md: "Q2", back_md: "A2" }),
      ]),
    );
    const user = userEvent.setup();

    render(<SectionCards courseId="course-1" chapterLabel="Fractions" sectionId="sec-1" />);

    expect(await screen.findByText("Q1")).toBeInTheDocument();
    expect(screen.getByText("Q2")).toBeInTheDocument();
    expect(screen.queryByText("A1")).not.toBeInTheDocument();
    expect(screen.queryByText("A2")).not.toBeInTheDocument();

    const revealButtons = screen.getAllByRole("button", { name: /show answer/i });
    await user.click(revealButtons[0]);

    expect(await screen.findByText("A1")).toBeInTheDocument();
    expect(screen.queryByText("A2")).not.toBeInTheDocument();
  });

  it("shows an 'edited' chip only for user-origin cards", async () => {
    mockedListCards.mockResolvedValue(
      ok([
        makeCard({ id: "c1", front_md: "Generated card", origin: "generated" }),
        makeCard({ id: "c2", front_md: "User card", origin: "user" }),
      ]),
    );

    render(<SectionCards courseId="course-1" chapterLabel="Fractions" sectionId="sec-1" />);

    await screen.findByText("Generated card");
    expect(screen.getAllByText("edited")).toHaveLength(1);
  });

  it("refetches and shows fresh cards the instant the cardsBus reports this section's job settled", async () => {
    mockedListCards
      .mockResolvedValueOnce(ok([]))
      .mockResolvedValueOnce(ok([makeCard({ id: "new-card", front_md: "Freshly generated" })]));

    render(<SectionCards courseId="course-1" chapterLabel="Fractions" sectionId="sec-1" />);
    await waitFor(() => expect(mockedListCards).toHaveBeenCalledTimes(1));

    act(() => {
      notifyCardsSettled("sec-1");
    });

    expect(await screen.findByText("Freshly generated")).toBeInTheDocument();
  });

  it("ignores a cardsBus settle notification for a different section", async () => {
    mockedListCards.mockResolvedValue(ok([makeCard({ front_md: "Unrelated" })]));

    render(<SectionCards courseId="course-1" chapterLabel="Fractions" sectionId="sec-1" />);
    await screen.findByText("Unrelated");
    mockedListCards.mockClear();

    act(() => {
      notifyCardsSettled("some-other-section");
    });

    expect(mockedListCards).not.toHaveBeenCalled();
  });

  it("cards appear here immediately once CardsCTA's generation job settles via SSE, no navigation", async () => {
    mockedListCards
      .mockResolvedValueOnce(ok([])) // CardsCTA's initial load
      .mockResolvedValueOnce(ok([])) // SectionCards' initial load
      .mockResolvedValueOnce(ok([makeCard({ front_md: "Card from generation" })])) // CardsCTA refetch
      .mockResolvedValueOnce(ok([makeCard({ front_md: "Card from generation" })])); // SectionCards refetch
    mockedGenerateCards.mockResolvedValue(ok({ job_id: "job-1" }, 202));
    const originalEventSource = globalThis.EventSource;
    FakeEventSource.instances = [];
    globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;

    const user = userEvent.setup();
    render(
      <>
        <CardsCTA sectionId="sec-1" />
        <SectionCards courseId="course-1" chapterLabel="Fractions" sectionId="sec-1" />
      </>,
    );

    await user.click(await screen.findByRole("button", { name: /generate flashcards/i }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      FakeEventSource.instances[0].emit("update", {
        id: "job-1",
        status: "succeeded",
        progress: { stage: "done", pct: 100, message: "done" },
      });
    });

    expect(await screen.findByText("Card from generation")).toBeInTheDocument();
    globalThis.EventSource = originalEventSource;
  });

  it("editing a card: Save PATCHes and swaps the card in place under its new id, without refetching the list", async () => {
    mockedListCards.mockResolvedValue(ok([makeCard({ id: "old-id", front_md: "Old front" })]));
    mockedPatchCard.mockResolvedValue(
      ok(makeCard({ id: "new-id", front_md: "New front", back_md: "New back", origin: "user" })),
    );
    const user = userEvent.setup();

    render(<SectionCards courseId="course-1" chapterLabel="Fractions" sectionId="sec-1" />);
    await screen.findByText("Old front");

    await user.click(screen.getByRole("button", { name: /^edit$/i }));
    const textboxes = screen.getAllByRole("textbox");
    await user.clear(textboxes[0]);
    await user.type(textboxes[0], "New front");
    await user.clear(textboxes[1]);
    await user.type(textboxes[1], "New back");
    mockedListCards.mockClear();
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(mockedPatchCard).toHaveBeenCalledWith("old-id", {
      front_md: "New front",
      back_md: "New back",
    });
    expect(await screen.findByText("New front")).toBeInTheDocument();
    expect(screen.queryByText("Old front")).not.toBeInTheDocument();
    expect(screen.getByText("edited")).toBeInTheDocument();
    // The PATCH response is the truth — no extra list_cards call.
    expect(mockedListCards).not.toHaveBeenCalled();
  });

  it("cancelling an edit restores the original card, unchanged", async () => {
    mockedListCards.mockResolvedValue(ok([makeCard({ front_md: "Original front" })]));
    const user = userEvent.setup();

    render(<SectionCards courseId="course-1" chapterLabel="Fractions" sectionId="sec-1" />);
    await screen.findByText("Original front");

    await user.click(screen.getByRole("button", { name: /^edit$/i }));
    const textboxes = screen.getAllByRole("textbox");
    await user.type(textboxes[0], " edited but not saved");
    await user.click(screen.getByRole("button", { name: /^cancel$/i }));

    expect(await screen.findByText("Original front")).toBeInTheDocument();
    expect(mockedPatchCard).not.toHaveBeenCalled();
  });

  it("shows an inline duplicate error on a 409 from save, and stays in edit mode", async () => {
    mockedListCards.mockResolvedValue(ok([makeCard({ front_md: "Front" })]));
    mockedPatchCard.mockResolvedValue(err(409));
    const user = userEvent.setup();

    render(<SectionCards courseId="course-1" chapterLabel="Fractions" sectionId="sec-1" />);
    await screen.findByText("Front");

    await user.click(screen.getByRole("button", { name: /^edit$/i }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(await screen.findByText(/this duplicates an existing card/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^save$/i })).toBeInTheDocument();
  });

  it("delete: the confirm dialog mentions review history, and confirming removes the card and fires notifyReviewSettled", async () => {
    mockedListCards.mockResolvedValue(ok([makeCard({ id: "card-to-delete", front_md: "Doomed" })]));
    mockedDeleteCard.mockResolvedValue({ ok: true, status: 204 });
    const user = userEvent.setup();

    render(<SectionCards courseId="course-1" chapterLabel="Fractions" sectionId="sec-1" />);
    await screen.findByText("Doomed");

    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    expect(screen.getByText(/removes its review history/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^confirm$/i }));

    expect(mockedDeleteCard).toHaveBeenCalledWith("card-to-delete");
    await waitFor(() => expect(screen.queryByText("Doomed")).not.toBeInTheDocument());
    expect(mockedNotifyReviewSettled).toHaveBeenCalled();
  });

  it("cancelling the delete confirmation keeps the card and never calls deleteCard", async () => {
    mockedListCards.mockResolvedValue(ok([makeCard({ front_md: "Keep me" })]));
    const user = userEvent.setup();

    render(<SectionCards courseId="course-1" chapterLabel="Fractions" sectionId="sec-1" />);
    await screen.findByText("Keep me");

    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    await user.click(screen.getByRole("button", { name: /^cancel$/i }));

    expect(screen.getByText("Keep me")).toBeInTheDocument();
    expect(mockedDeleteCard).not.toHaveBeenCalled();
  });

  it("does not let a reader-level shortcut fire while a card's edit textarea is focused", async () => {
    mockedListCards.mockResolvedValue(ok([makeCard({ front_md: "Front" })]));
    const onJ = vi.fn();
    const user = userEvent.setup();

    render(
      <>
        <ReaderShortcutProbe onJ={onJ} />
        <SectionCards courseId="course-1" chapterLabel="Fractions" sectionId="sec-1" />
      </>,
    );
    await screen.findByText("Front");

    await user.click(screen.getByRole("button", { name: /^edit$/i }));
    const [frontTextarea] = screen.getAllByRole("textbox");
    await user.type(frontTextarea, "j");

    expect(onJ).not.toHaveBeenCalled();
  });

  it("shows all four grade choices after an inline answer is revealed", async () => {
    mockedListCards.mockResolvedValue(ok([makeCard({ id: "card-1" })]));
    mockedGetReviewQueue.mockResolvedValue(reviewQueue([makeReviewCard({ id: "card-1" })]));
    const user = userEvent.setup();

    render(<SectionCards courseId="course-1" chapterLabel="Fractions" sectionId="sec-1" />);

    await user.click(await screen.findByRole("button", { name: "Show answer" }));

    expect(screen.getByRole("button", { name: /again/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /hard/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /good/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /easy/i })).toBeVisible();
  });

  it("links chapter review to every card in the current chapter", async () => {
    mockedListCards.mockResolvedValue(ok([makeCard({ id: "card-1" })]));

    render(
      <SectionCards courseId="course-1" chapterLabel="Fractions & Ratios" sectionId="sec-1" />,
    );

    expect(await screen.findByRole("link", { name: "Review this chapter" })).toHaveAttribute(
      "href",
      "/review?course=course-1&scope=all&chapter=Fractions%20%26%20Ratios",
    );
    expect(mockedGetReviewQueue).toHaveBeenCalledWith("course-1", {
      scope: "all",
      chapterLabel: "Fractions & Ratios",
      limit: 200,
    });
  });

  it("keeps a failed inline grade revealed and retryable", async () => {
    mockedListCards.mockResolvedValue(ok([makeCard({ id: "card-1", back_md: "Retryable answer" })]));
    mockedGetReviewQueue.mockResolvedValue(reviewQueue([makeReviewCard({ id: "card-1" })]));
    mockedGradeCardAndNotify.mockResolvedValue(failedGradeResult());
    const user = userEvent.setup();

    render(<SectionCards courseId="course-1" chapterLabel="Fractions" sectionId="sec-1" />);

    await user.click(await screen.findByRole("button", { name: "Show answer" }));
    await user.click(screen.getByRole("button", { name: /again/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not save/i);
    expect(screen.getByText("Retryable answer")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /again/i })).toBeEnabled();
  });

  it("keeps a successful inline grade saved and locked", async () => {
    mockedListCards.mockResolvedValue(ok([makeCard({ id: "card-1", back_md: "Saved answer" })]));
    mockedGetReviewQueue.mockResolvedValue(reviewQueue([makeReviewCard({ id: "card-1" })]));
    const user = userEvent.setup();

    render(<SectionCards courseId="course-1" chapterLabel="Fractions" sectionId="sec-1" />);

    await user.click(await screen.findByRole("button", { name: "Show answer" }));
    await user.click(screen.getByRole("button", { name: /easy/i }));

    expect(await screen.findByText("Saved as Easy.")).toBeInTheDocument();
    expect(screen.getByText("Saved answer")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /easy/i })).toBeDisabled();
  });

  it("keeps review controls wired to the new card id after editing creates a content-addressed card", async () => {
    mockedListCards.mockResolvedValue(ok([makeCard({ id: "old-id", front_md: "Old front" })]));
    mockedGetReviewQueue.mockResolvedValue(reviewQueue([makeReviewCard({ id: "old-id" })]));
    mockedPatchCard.mockResolvedValue(
      ok(makeCard({ id: "new-id", front_md: "New front", back_md: "New answer", origin: "user" })),
    );
    const user = userEvent.setup();

    render(<SectionCards courseId="course-1" chapterLabel="Fractions" sectionId="sec-1" />);
    await screen.findByText("Old front");

    await user.click(screen.getByRole("button", { name: /^edit$/i }));
    const [frontTextarea, backTextarea] = screen.getAllByRole("textbox");
    await user.clear(frontTextarea);
    await user.type(frontTextarea, "New front");
    await user.clear(backTextarea);
    await user.type(backTextarea, "New answer");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await user.click(await screen.findByRole("button", { name: "Show answer" }));
    await user.click(screen.getByRole("button", { name: /good/i }));

    expect(await screen.findByText("Saved as Good.")).toBeInTheDocument();
    expect(mockedGradeCardAndNotify).toHaveBeenCalledWith("new-id", 3, expect.any(Number));
  });

  it("keeps editable cards visible when review metadata fails and retries metadata loading", async () => {
    mockedListCards.mockResolvedValue(ok([makeCard({ id: "card-1", front_md: "Editable front" })]));
    mockedGetReviewQueue.mockResolvedValueOnce(err(503)).mockResolvedValueOnce(reviewQueue());
    const user = userEvent.setup();

    render(<SectionCards courseId="course-1" chapterLabel="Fractions" sectionId="sec-1" />);

    expect(await screen.findByText("Editable front")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^edit$/i })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/loading review metadata/i);

    await user.click(screen.getByRole("button", { name: /retry review metadata/i }));
    await user.click(await screen.findByRole("button", { name: "Show answer" }));

    expect(screen.getByRole("button", { name: /again/i })).toBeVisible();
    expect(mockedGetReviewQueue).toHaveBeenCalledTimes(2);
  });

  it("omits the chapter review link when the section has no chapter label", async () => {
    mockedListCards.mockResolvedValue(ok([makeCard({ id: "card-1" })]));

    render(<SectionCards courseId="course-1" chapterLabel={null} sectionId="sec-1" />);

    await screen.findByText("Front text");
    expect(screen.queryByRole("link", { name: "Review this chapter" })).not.toBeInTheDocument();
    expect(mockedGetReviewQueue).not.toHaveBeenCalled();
  });

  it("loads exact review metadata for front-matter cards without a chapter review link", async () => {
    mockedListCards.mockResolvedValue(
      ok([
        makeCard({ id: "card-1", front_md: "Front matter one" }),
        makeCard({ id: "card-2", front_md: "Front matter two" }),
      ]),
    );
    mockedGetReviewSelection.mockResolvedValue(
      reviewSelection([makeReviewCard({ id: "card-2", front_md: "Front matter two" })]),
    );
    const user = userEvent.setup();

    render(<SectionCards courseId="course-1" chapterLabel={null} sectionId="sec-1" />);

    expect(await screen.findByText("Front matter one")).toBeInTheDocument();
    expect(screen.getByText("Front matter two")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Review this chapter" })).not.toBeInTheDocument();
    expect(mockedGetReviewQueue).not.toHaveBeenCalled();
    expect(mockedGetReviewSelection).toHaveBeenCalledWith("course-1", ["card-1", "card-2"]);

    const revealButtons = screen.getAllByRole("button", { name: "Show answer" });
    await user.click(revealButtons[0]);
    expect(screen.queryByRole("button", { name: /again/i })).not.toBeInTheDocument();

    await user.click(revealButtons[1]);
    expect(screen.getByRole("button", { name: /again/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /hard/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /good/i })).toBeVisible();
    expect(screen.getByRole("button", { name: /easy/i })).toBeVisible();
  });

  it("keeps front-matter cards editable when exact review metadata fails and retries metadata loading", async () => {
    mockedListCards.mockResolvedValue(ok([makeCard({ id: "card-1", front_md: "Preface card" })]));
    mockedGetReviewSelection.mockResolvedValueOnce(err(503)).mockResolvedValueOnce(reviewSelection());
    const user = userEvent.setup();

    render(<SectionCards courseId="course-1" chapterLabel={null} sectionId="sec-1" />);

    expect(await screen.findByText("Preface card")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^edit$/i })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/loading review metadata/i);

    await user.click(screen.getByRole("button", { name: /retry review metadata/i }));
    await user.click(await screen.findByRole("button", { name: "Show answer" }));

    expect(screen.getByRole("button", { name: /again/i })).toBeVisible();
    expect(mockedGetReviewSelection).toHaveBeenCalledTimes(2);
  });
});
