"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  createNote as apiCreateNote,
  deleteNote as apiDeleteNote,
  listNotes as apiListNotes,
  updateNote as apiUpdateNote,
  type NoteOut,
} from "@/lib/api/client";
import { describeError } from "@/lib/api/errors";

type LoadOutcome = { ok: true; all: NoteOut[] } | { ok: false; error: string };
type Params = { courseId: string; sectionId: string };

/** Pure fetch of the course-wide note list — no setState — shared by the
 * param-change effect and reload(), mirroring useHighlights.fetchHighlights. */
async function fetchNotes(courseId: string): Promise<LoadOutcome> {
  const { data, status, ok } = await apiListNotes(courseId);
  if (!ok || !data) {
    return { ok: false, error: describeError(status, "Loading notes").message };
  }
  return { ok: true, all: data };
}

export interface UseNotes {
  /** Notes for the ACTIVE section only (course list filtered client-side). */
  notes: NoteOut[];
  error: string | null;
  createNote: (page: number, anchorY: number, noteMd: string) => Promise<NoteOut | null>;
  updateNote: (id: string, noteMd: string) => Promise<void>;
  deleteNote: (id: string) => Promise<void>;
  reload: () => void;
}

/**
 * Per-section positional-note state + CRUD, a structural twin of useHighlights
 * (course-scoped API, filtered to sectionId client-side; a course-wide
 * `cacheRef` is the single source of truth, mutated id-scoped never wholesale;
 * `paramsRef`/`syncDisplayed` keep an async continuation landing on the
 * currently-displayed section). Simpler than useHighlights: notes have no
 * color and note_md is required, so there is no null-clearing path.
 */
export function useNotes(courseId: string, sectionId: string): UseNotes {
  const [notes, setNotes] = useState<NoteOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const cacheRef = useRef<NoteOut[]>([]);
  const paramsRef = useRef<Params>({ courseId, sectionId });

  useEffect(() => {
    paramsRef.current = { courseId, sectionId };
  }, [courseId, sectionId]);

  const syncDisplayed = useCallback(() => {
    setNotes(cacheRef.current.filter((n) => n.section_id === paramsRef.current.sectionId));
  }, []);

  useEffect(() => {
    let active = true;
    fetchNotes(courseId).then((result) => {
      if (!active) return;
      if (!result.ok) {
        setError(result.error);
        return;
      }
      if (paramsRef.current.courseId !== courseId) return;
      cacheRef.current = result.all;
      setError(null);
      syncDisplayed();
    });
    return () => {
      active = false;
    };
  }, [courseId, sectionId, syncDisplayed]);

  const reload = useCallback(() => {
    const requestedCourseId = courseId;
    fetchNotes(requestedCourseId).then((result) => {
      if (!result.ok) {
        setError(result.error);
        return;
      }
      if (paramsRef.current.courseId !== requestedCourseId) return;
      cacheRef.current = result.all;
      setError(null);
      syncDisplayed();
    });
  }, [courseId, syncDisplayed]);

  const createNote = useCallback(
    async (page: number, anchorY: number, noteMd: string): Promise<NoteOut | null> => {
      const { data, status, ok } = await apiCreateNote(courseId, {
        section_id: sectionId,
        page,
        anchor_y: anchorY,
        note_md: noteMd,
        surface: "pdf",
      });
      if (!ok || !data) {
        setError(describeError(status, "Creating note").message);
        return null;
      }
      setError(null);
      cacheRef.current = [...cacheRef.current, data];
      syncDisplayed();
      return data;
    },
    [courseId, sectionId, syncDisplayed],
  );

  const updateNote = useCallback(
    async (id: string, noteMd: string): Promise<void> => {
      const original = cacheRef.current.find((n) => n.id === id);
      if (!original) return;
      const optimistic: NoteOut = { ...original, note_md: noteMd };
      cacheRef.current = cacheRef.current.map((n) => (n.id === id ? optimistic : n));
      setError(null);
      syncDisplayed();

      const { data, status, ok } = await apiUpdateNote(id, { note_md: noteMd });
      if (!ok || !data) {
        cacheRef.current = cacheRef.current.map((n) => (n.id === id ? original : n));
        setError(describeError(status, "Updating note").message);
        syncDisplayed();
        return;
      }
      cacheRef.current = cacheRef.current.map((n) => (n.id === id ? data : n));
      syncDisplayed();
    },
    [syncDisplayed],
  );

  const deleteNote = useCallback(
    async (id: string): Promise<void> => {
      const index = cacheRef.current.findIndex((n) => n.id === id);
      if (index === -1) return;
      const original = cacheRef.current[index];
      cacheRef.current = cacheRef.current.filter((n) => n.id !== id);
      setError(null);
      syncDisplayed();

      const { ok, status } = await apiDeleteNote(id);
      if (!ok) {
        const restored = [...cacheRef.current];
        restored.splice(index, 0, original);
        cacheRef.current = restored;
        setError(describeError(status, "Deleting note").message);
        syncDisplayed();
      }
    },
    [syncDisplayed],
  );

  return { notes, error, createNote, updateNote, deleteNote, reload };
}
