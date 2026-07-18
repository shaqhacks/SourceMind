import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { HighlightOut } from "@/lib/api/client";
import {
  createHighlight,
  deleteHighlight,
  listHighlights,
  updateHighlight,
} from "@/lib/api/client";
import { useHighlights } from "@/lib/hooks/useHighlights";

import { err, ok } from "../support/api-result";

vi.mock("@/lib/api/client", () => ({
  listHighlights: vi.fn(),
  createHighlight: vi.fn(),
  updateHighlight: vi.fn(),
  deleteHighlight: vi.fn(),
}));

const mockedListHighlights = vi.mocked(listHighlights);
const mockedCreateHighlight = vi.mocked(createHighlight);
const mockedUpdateHighlight = vi.mocked(updateHighlight);
const mockedDeleteHighlight = vi.mocked(deleteHighlight);

function makeHighlight(overrides: Partial<HighlightOut> = {}): HighlightOut {
  return {
    id: "hl-1",
    course_id: "course-1",
    section_id: "sec-1",
    exact: "quoted text",
    prefix: "before ",
    suffix: " after",
    occurrence: 0,
    page: 3,
    color: "yellow",
    note_md: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("useHighlights", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("loads the course's highlights and filters to the active section", async () => {
    mockedListHighlights.mockResolvedValue(
      ok([
        makeHighlight({ id: "hl-1", section_id: "sec-1" }),
        makeHighlight({ id: "hl-2", section_id: "sec-2" }),
      ]),
    );

    const { result } = renderHook(() => useHighlights("course-1", "sec-1"));

    await waitFor(() => expect(result.current.highlights).toHaveLength(1));
    expect(result.current.highlights[0].id).toBe("hl-1");
    expect(result.current.error).toBeNull();
    expect(mockedListHighlights).toHaveBeenCalledWith("course-1");
  });

  it("createFromSelector POSTs a HighlightIn built from the selector and appends the result", async () => {
    mockedListHighlights.mockResolvedValue(ok([]));
    const created = makeHighlight({ id: "hl-new", exact: "new quote" });
    mockedCreateHighlight.mockResolvedValue(ok(created, 201));

    const { result } = renderHook(() => useHighlights("course-1", "sec-1"));
    await waitFor(() => expect(mockedListHighlights).toHaveBeenCalled());

    let returned: HighlightOut | null = null;
    await act(async () => {
      returned = await result.current.createFromSelector(
        { exact: "new quote", prefix: "pre", suffix: "post", occurrence: 0 },
        "green",
        5,
      );
    });

    expect(mockedCreateHighlight).toHaveBeenCalledWith("course-1", {
      section_id: "sec-1",
      exact: "new quote",
      prefix: "pre",
      suffix: "post",
      occurrence: 0,
      page: 5,
      color: "green",
    });
    expect(returned).toEqual(created);
    expect(result.current.highlights).toContainEqual(created);
    expect(result.current.error).toBeNull();
  });

  it("a failed create sets error and does not append anything", async () => {
    mockedListHighlights.mockResolvedValue(ok([]));
    mockedCreateHighlight.mockResolvedValue(err(500));

    const { result } = renderHook(() => useHighlights("course-1", "sec-1"));
    await waitFor(() => expect(mockedListHighlights).toHaveBeenCalled());

    let returned: HighlightOut | null = makeHighlight();
    await act(async () => {
      returned = await result.current.createFromSelector(
        { exact: "x", prefix: "", suffix: "", occurrence: 0 },
        "yellow",
        null,
      );
    });

    expect(returned).toBeNull();
    expect(result.current.highlights).toHaveLength(0);
    expect(result.current.error).not.toBeNull();
  });

  it("updateOne PATCHes and reflects the new note/color once the server responds", async () => {
    const original = makeHighlight({ id: "hl-1", color: "yellow", note_md: null });
    mockedListHighlights.mockResolvedValue(ok([original]));
    const updated = { ...original, color: "blue" as const, note_md: "a note" };
    mockedUpdateHighlight.mockResolvedValue(ok(updated));

    const { result } = renderHook(() => useHighlights("course-1", "sec-1"));
    await waitFor(() => expect(result.current.highlights).toHaveLength(1));

    await act(async () => {
      await result.current.updateOne("hl-1", { color: "blue", note_md: "a note" });
    });

    expect(mockedUpdateHighlight).toHaveBeenCalledWith("hl-1", { color: "blue", note_md: "a note" });
    expect(result.current.highlights[0].color).toBe("blue");
    expect(result.current.highlights[0].note_md).toBe("a note");
    expect(result.current.error).toBeNull();
  });

  it("a failed updateOne rolls back the optimistic change and sets error", async () => {
    const original = makeHighlight({ id: "hl-1", color: "yellow", note_md: null });
    mockedListHighlights.mockResolvedValue(ok([original]));
    mockedUpdateHighlight.mockResolvedValue(err(500));

    const { result } = renderHook(() => useHighlights("course-1", "sec-1"));
    await waitFor(() => expect(result.current.highlights).toHaveLength(1));

    await act(async () => {
      await result.current.updateOne("hl-1", { color: "pink" });
    });

    expect(result.current.highlights[0].color).toBe("yellow");
    expect(result.current.error).not.toBeNull();
  });

  it("deleteOne removes the highlight once the server confirms", async () => {
    const target = makeHighlight({ id: "hl-1" });
    mockedListHighlights.mockResolvedValue(ok([target]));
    mockedDeleteHighlight.mockResolvedValue({ ok: true, status: 204 });

    const { result } = renderHook(() => useHighlights("course-1", "sec-1"));
    await waitFor(() => expect(result.current.highlights).toHaveLength(1));

    await act(async () => {
      await result.current.deleteOne("hl-1");
    });

    expect(mockedDeleteHighlight).toHaveBeenCalledWith("hl-1");
    expect(result.current.highlights).toHaveLength(0);
    expect(result.current.error).toBeNull();
  });

  it("a failed deleteOne restores the highlight and sets error", async () => {
    const target = makeHighlight({ id: "hl-1" });
    mockedListHighlights.mockResolvedValue(ok([target]));
    mockedDeleteHighlight.mockResolvedValue(err(500));

    const { result } = renderHook(() => useHighlights("course-1", "sec-1"));
    await waitFor(() => expect(result.current.highlights).toHaveLength(1));

    await act(async () => {
      await result.current.deleteOne("hl-1");
    });

    expect(result.current.highlights).toHaveLength(1);
    expect(result.current.error).not.toBeNull();
  });

  it("reload() re-fetches the course list and refreshes the active section's slice", async () => {
    mockedListHighlights
      .mockResolvedValueOnce(ok([makeHighlight({ id: "hl-1" })]))
      .mockResolvedValueOnce(ok([makeHighlight({ id: "hl-1" }), makeHighlight({ id: "hl-2" })]));

    const { result } = renderHook(() => useHighlights("course-1", "sec-1"));
    await waitFor(() => expect(result.current.highlights).toHaveLength(1));

    act(() => {
      result.current.reload();
    });

    await waitFor(() => expect(result.current.highlights).toHaveLength(2));
    expect(mockedListHighlights).toHaveBeenCalledTimes(2);
  });

  it("re-fetches when the active section changes", async () => {
    mockedListHighlights.mockResolvedValue(
      ok([
        makeHighlight({ id: "hl-1", section_id: "sec-1" }),
        makeHighlight({ id: "hl-2", section_id: "sec-2" }),
      ]),
    );

    const { result, rerender } = renderHook(
      ({ sectionId }: { sectionId: string }) => useHighlights("course-1", sectionId),
      { initialProps: { sectionId: "sec-1" } },
    );

    await waitFor(() => expect(result.current.highlights).toEqual([expect.objectContaining({ id: "hl-1" })]));

    rerender({ sectionId: "sec-2" });

    await waitFor(() => expect(result.current.highlights).toEqual([expect.objectContaining({ id: "hl-2" })]));
  });

  it("a stale updateOne resolution does not clobber a section the user has since navigated away from", async () => {
    const helloA = makeHighlight({ id: "hl-a", section_id: "sec-a", color: "yellow" });
    const helloB = makeHighlight({ id: "hl-b", section_id: "sec-b", color: "yellow" });
    const patchedA = { ...helloA, color: "blue" as const };

    // Three sequenced course-wide loads, one per param-change effect run:
    // mount at sec-a, rerender to sec-b (server not patched yet), rerender
    // back to sec-a (server now reflects the confirmed PATCH).
    mockedListHighlights
      .mockResolvedValueOnce(ok([helloA, helloB]))
      .mockResolvedValueOnce(ok([helloA, helloB]))
      .mockResolvedValueOnce(ok([patchedA, helloB]));

    let resolvePatch!: (result: Awaited<ReturnType<typeof updateHighlight>>) => void;
    mockedUpdateHighlight.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePatch = resolve;
        }),
    );

    const { result, rerender } = renderHook(
      ({ sectionId }: { sectionId: string }) => useHighlights("course-1", sectionId),
      { initialProps: { sectionId: "sec-a" } },
    );

    await waitFor(() => expect(result.current.highlights).toEqual([expect.objectContaining({ id: "hl-a" })]));

    let updatePromise!: Promise<void>;
    act(() => {
      updatePromise = result.current.updateOne("hl-a", { color: "blue" });
    });

    // Optimistic update landed while sec-a was still displayed.
    expect(result.current.highlights[0].color).toBe("blue");

    // Navigate away before the PATCH resolves.
    rerender({ sectionId: "sec-b" });
    await waitFor(() => expect(result.current.highlights).toEqual([expect.objectContaining({ id: "hl-b" })]));

    // The stale PATCH for sec-a's highlight resolves now, after navigation.
    await act(async () => {
      resolvePatch(ok(patchedA));
      await updatePromise;
    });

    // Displayed highlights must still reflect section B — not clobbered
    // back to section A's data by the late-resolving mutation.
    expect(result.current.highlights).toEqual([expect.objectContaining({ id: "hl-b" })]);
    expect(result.current.error).toBeNull();

    // The cache's A row was still correctly updated: navigating back to A
    // shows the confirmed patched color.
    rerender({ sectionId: "sec-a" });
    await waitFor(() =>
      expect(result.current.highlights).toEqual([expect.objectContaining({ id: "hl-a", color: "blue" })]),
    );
  });

  it("a failed updateOne rollback does not discard a different id's concurrently-confirmed update", async () => {
    const hl1 = makeHighlight({ id: "hl-1", color: "yellow" });
    const hl2 = makeHighlight({ id: "hl-2", color: "yellow" });
    mockedListHighlights.mockResolvedValue(ok([hl1, hl2]));

    let resolveUpdate1!: (result: Awaited<ReturnType<typeof updateHighlight>>) => void;
    let resolveUpdate2!: (result: Awaited<ReturnType<typeof updateHighlight>>) => void;
    mockedUpdateHighlight.mockImplementation((id) => {
      if (id === "hl-1") {
        return new Promise((resolve) => {
          resolveUpdate1 = resolve;
        });
      }
      return new Promise((resolve) => {
        resolveUpdate2 = resolve;
      });
    });

    const { result } = renderHook(() => useHighlights("course-1", "sec-1"));
    await waitFor(() => expect(result.current.highlights).toHaveLength(2));

    let promise1!: Promise<void>;
    let promise2!: Promise<void>;
    act(() => {
      promise1 = result.current.updateOne("hl-1", { color: "pink" });
      promise2 = result.current.updateOne("hl-2", { color: "blue" });
    });

    // Both optimistic updates landed independently.
    expect(result.current.highlights.find((h) => h.id === "hl-1")?.color).toBe("pink");
    expect(result.current.highlights.find((h) => h.id === "hl-2")?.color).toBe("blue");

    // hl-2 confirms first...
    const confirmed2 = { ...hl2, color: "blue" as const };
    await act(async () => {
      resolveUpdate2(ok(confirmed2));
      await promise2;
    });
    expect(result.current.highlights.find((h) => h.id === "hl-2")?.color).toBe("blue");

    // ...then hl-1 fails and rolls back. Its rollback must not wipe hl-2's
    // already-confirmed change.
    await act(async () => {
      resolveUpdate1(err(500));
      await promise1;
    });

    expect(result.current.highlights.find((h) => h.id === "hl-1")?.color).toBe("yellow");
    expect(result.current.highlights.find((h) => h.id === "hl-2")?.color).toBe("blue");
    expect(result.current.error).not.toBeNull();
  });
});
