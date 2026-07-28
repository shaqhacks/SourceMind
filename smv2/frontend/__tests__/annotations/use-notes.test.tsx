import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { NoteOut } from "@/lib/api/client";
import { createNote, deleteNote, listNotes, updateNote } from "@/lib/api/client";
import { useNotes } from "@/lib/hooks/useNotes";

import { err, ok } from "../support/api-result";

vi.mock("@/lib/api/client", () => ({
  listNotes: vi.fn(),
  createNote: vi.fn(),
  updateNote: vi.fn(),
  deleteNote: vi.fn(),
}));

const mockedListNotes = vi.mocked(listNotes);
const mockedCreateNote = vi.mocked(createNote);
const mockedUpdateNote = vi.mocked(updateNote);
const mockedDeleteNote = vi.mocked(deleteNote);

function makeNote(overrides: Partial<NoteOut> = {}): NoteOut {
  return {
    id: "note-1",
    course_id: "course-1",
    section_id: "sec-1",
    surface: "pdf",
    page: 2,
    anchor_y: 0.25,
    note_md: "a margin note",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("useNotes", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("loads the course's notes and filters to the active section", async () => {
    mockedListNotes.mockResolvedValue(
      ok([
        makeNote({ id: "note-1", section_id: "sec-1" }),
        makeNote({ id: "note-2", section_id: "sec-2" }),
      ]),
    );

    const { result } = renderHook(() => useNotes("course-1", "sec-1"));

    await waitFor(() => expect(result.current.notes).toHaveLength(1));
    expect(result.current.notes[0].id).toBe("note-1");
    expect(result.current.error).toBeNull();
    expect(mockedListNotes).toHaveBeenCalledWith("course-1");
  });

  it("createNote POSTs a NoteIn and appends the result on success", async () => {
    mockedListNotes.mockResolvedValue(ok([]));
    const created = makeNote({ id: "note-new", note_md: "new note" });
    mockedCreateNote.mockResolvedValue(ok(created, 201));

    const { result } = renderHook(() => useNotes("course-1", "sec-1"));
    await waitFor(() => expect(mockedListNotes).toHaveBeenCalled());

    let returned: NoteOut | null = null;
    await act(async () => {
      returned = await result.current.createNote(2, 0.4, "new note");
    });

    expect(mockedCreateNote).toHaveBeenCalledWith("course-1", {
      section_id: "sec-1",
      page: 2,
      anchor_y: 0.4,
      note_md: "new note",
      surface: "pdf",
    });
    expect(returned).toEqual(created);
    expect(result.current.notes).toContainEqual(created);
    expect(result.current.error).toBeNull();
  });

  it("a failed createNote sets error and does not append anything", async () => {
    mockedListNotes.mockResolvedValue(ok([]));
    mockedCreateNote.mockResolvedValue(err(500));

    const { result } = renderHook(() => useNotes("course-1", "sec-1"));
    await waitFor(() => expect(mockedListNotes).toHaveBeenCalled());

    let returned: NoteOut | null = makeNote();
    await act(async () => {
      returned = await result.current.createNote(1, 0.1, "x");
    });

    expect(returned).toBeNull();
    expect(result.current.notes).toHaveLength(0);
    expect(result.current.error).not.toBeNull();
  });

  it("updateNote PATCHes and reflects the new note_md once the server responds", async () => {
    const original = makeNote({ id: "note-1", note_md: "before" });
    mockedListNotes.mockResolvedValue(ok([original]));
    const updated = { ...original, note_md: "after" };
    mockedUpdateNote.mockResolvedValue(ok(updated));

    const { result } = renderHook(() => useNotes("course-1", "sec-1"));
    await waitFor(() => expect(result.current.notes).toHaveLength(1));

    await act(async () => {
      await result.current.updateNote("note-1", "after");
    });

    expect(mockedUpdateNote).toHaveBeenCalledWith("note-1", { note_md: "after" });
    expect(result.current.notes[0].note_md).toBe("after");
    expect(result.current.error).toBeNull();
  });

  it("a failed updateNote rolls back note_md and sets error", async () => {
    const original = makeNote({ id: "note-1", note_md: "before" });
    mockedListNotes.mockResolvedValue(ok([original]));
    mockedUpdateNote.mockResolvedValue(err(500));

    const { result } = renderHook(() => useNotes("course-1", "sec-1"));
    await waitFor(() => expect(result.current.notes).toHaveLength(1));

    await act(async () => {
      await result.current.updateNote("note-1", "attempted edit");
    });

    expect(result.current.notes[0].note_md).toBe("before");
    expect(result.current.error).not.toBeNull();
  });

  it("deleteNote removes the note once the server confirms", async () => {
    const target = makeNote({ id: "note-1" });
    mockedListNotes.mockResolvedValue(ok([target]));
    mockedDeleteNote.mockResolvedValue({ ok: true, status: 204 });

    const { result } = renderHook(() => useNotes("course-1", "sec-1"));
    await waitFor(() => expect(result.current.notes).toHaveLength(1));

    await act(async () => {
      await result.current.deleteNote("note-1");
    });

    expect(mockedDeleteNote).toHaveBeenCalledWith("note-1");
    expect(result.current.notes).toHaveLength(0);
    expect(result.current.error).toBeNull();
  });

  it("a failed deleteNote restores the note and sets error", async () => {
    const target = makeNote({ id: "note-1" });
    mockedListNotes.mockResolvedValue(ok([target]));
    mockedDeleteNote.mockResolvedValue(err(500));

    const { result } = renderHook(() => useNotes("course-1", "sec-1"));
    await waitFor(() => expect(result.current.notes).toHaveLength(1));

    await act(async () => {
      await result.current.deleteNote("note-1");
    });

    expect(result.current.notes).toHaveLength(1);
    expect(result.current.error).not.toBeNull();
  });

  it("reload() re-fetches the course list and refreshes the active section's slice", async () => {
    mockedListNotes
      .mockResolvedValueOnce(ok([makeNote({ id: "note-1" })]))
      .mockResolvedValueOnce(ok([makeNote({ id: "note-1" }), makeNote({ id: "note-2" })]));

    const { result } = renderHook(() => useNotes("course-1", "sec-1"));
    await waitFor(() => expect(result.current.notes).toHaveLength(1));

    act(() => {
      result.current.reload();
    });

    await waitFor(() => expect(result.current.notes).toHaveLength(2));
    expect(mockedListNotes).toHaveBeenCalledTimes(2);
  });

  it("re-fetches when the active section changes", async () => {
    mockedListNotes.mockResolvedValue(
      ok([
        makeNote({ id: "note-1", section_id: "sec-1" }),
        makeNote({ id: "note-2", section_id: "sec-2" }),
      ]),
    );

    const { result, rerender } = renderHook(
      ({ sectionId }: { sectionId: string }) => useNotes("course-1", sectionId),
      { initialProps: { sectionId: "sec-1" } },
    );

    await waitFor(() => expect(result.current.notes).toEqual([expect.objectContaining({ id: "note-1" })]));

    rerender({ sectionId: "sec-2" });

    await waitFor(() => expect(result.current.notes).toEqual([expect.objectContaining({ id: "note-2" })]));
  });
});
