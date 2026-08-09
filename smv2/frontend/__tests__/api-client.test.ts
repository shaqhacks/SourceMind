import { beforeEach, describe, expect, it, vi } from "vitest";

import { getReviewQueue, getReviewSelection } from "@/lib/api/client";
import { gradeCardAndNotify } from "@/lib/review/gradeCardAndNotify";
import { notifyReviewSettled } from "@/lib/review/reviewBus";

const { mockGet, mockPost } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
}));

vi.mock("openapi-fetch", () => ({
  default: vi.fn(() => ({
    GET: mockGet,
    POST: mockPost,
  })),
}));

vi.mock("@/lib/review/reviewBus", () => ({
  notifyReviewSettled: vi.fn(),
}));

const mockedNotifyReviewSettled = vi.mocked(notifyReviewSettled);

function response(status = 200): Response {
  return { status, ok: status >= 200 && status < 300 } as Response;
}

describe("api client review helpers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockResolvedValue({ data: { cards: [] }, response: response() });
    mockPost.mockResolvedValue({ data: { cards: [], missing_card_ids: [] }, response: response() });
  });

  it("sends review queue scope and chapter_label query parameters", async () => {
    await getReviewQueue("course-1", {
      limit: 25,
      scope: "needs_attention",
      chapterLabel: "Chapter 2",
    });

    expect(mockGet).toHaveBeenCalledWith("/api/courses/{course_id}/review/queue", {
      params: {
        path: { course_id: "course-1" },
        query: { limit: 25, scope: "needs_attention", chapter_label: "Chapter 2" },
      },
    });
  });

  it("omits undefined review queue options instead of sending empty values", async () => {
    await getReviewQueue("course-1", { limit: 10 });

    expect(mockGet).toHaveBeenCalledWith("/api/courses/{course_id}/review/queue", {
      params: {
        path: { course_id: "course-1" },
        query: { limit: 10 },
      },
    });
  });

  it("posts explicit review selection card ids in request order", async () => {
    await getReviewSelection("course-1", ["card-2", "card-1"]);

    expect(mockPost).toHaveBeenCalledWith("/api/courses/{course_id}/review/selection", {
      params: { path: { course_id: "course-1" } },
      body: { card_ids: ["card-2", "card-1"] },
    });
  });

  it("notifies review listeners only after a successful grade", async () => {
    mockPost.mockResolvedValueOnce({
      data: { next_due_at: "2026-08-10T00:00:00Z", remaining_due: 0 },
      response: response(200),
    });
    mockPost.mockResolvedValueOnce({ error: { detail: "unavailable" }, response: response(503) });

    await expect(gradeCardAndNotify("card-1", 3, 1200)).resolves.toMatchObject({ ok: true });
    await expect(gradeCardAndNotify("card-1", 1, 900)).resolves.toMatchObject({ ok: false });

    expect(mockedNotifyReviewSettled).toHaveBeenCalledTimes(1);
  });
});
