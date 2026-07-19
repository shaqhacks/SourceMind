"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  createHighlight,
  deleteHighlight,
  listHighlights,
  updateHighlight,
  type HighlightIn,
  type HighlightOut,
  type HighlightUpdateIn,
} from "@/lib/api/client";
import { describeError } from "@/lib/api/errors";
import type { QuoteSelector } from "@/lib/annotations/anchors";

export type HighlightColor = "yellow" | "green" | "blue" | "pink";

type LoadOutcome = { ok: true; all: HighlightOut[] } | { ok: false; error: string };

type Params = { courseId: string; sectionId: string };

/** Pure fetch of the course-wide highlight list — no setState — so both the
 * param-change effect (which needs its own `active`-flag guard against a
 * courseId/sectionId change or unmount racing an in-flight request) and
 * `reload()` (which doesn't) can share the same request logic without
 * duplicating it. Mirrors SectionCards.tsx's fetchCards helper. */
async function fetchHighlights(courseId: string): Promise<LoadOutcome> {
  const { data, status, ok } = await listHighlights(courseId);
  if (!ok || !data) {
    return { ok: false, error: describeError(status, "Loading highlights").message };
  }
  return { ok: true, all: data };
}

export interface UseHighlights {
  /** Highlights for the ACTIVE section only (course list filtered client-side). */
  highlights: HighlightOut[];
  error: string | null;
  createFromSelector: (
    sel: QuoteSelector,
    color: HighlightColor,
    page: number | null,
    surface: "source" | "pdf",
  ) => Promise<HighlightOut | null>;
  updateOne: (id: string, patch: HighlightUpdateIn) => Promise<void>;
  deleteOne: (id: string) => Promise<void>;
  reload: () => void;
}

/**
 * Per-section highlight state + CRUD. The API is course-scoped (there is no
 * per-section list endpoint), so every load fetches the whole course's
 * highlights and filters to `sectionId` client-side.
 *
 * `cacheRef` holds that COURSE-WIDE list and is the single source of truth;
 * `highlights` state is always a derived, section-filtered slice of it.
 * Every mutation edits `cacheRef` id-scoped — add one row, replace the row
 * matching an id, or remove the row matching an id — and NEVER replaces the
 * list wholesale (a whole-list snapshot/restore would let one mutation's
 * rollback discard a different id's concurrently-confirmed change). A full
 * overwrite of `cacheRef` only happens on an actual course-wide load (the
 * param-change effect, or `reload()`), and only once that load's captured
 * courseId is confirmed still current.
 *
 * `paramsRef` mirrors the latest (courseId, sectionId) outside of any single
 * callback's closure, kept in sync by its own effect. `syncDisplayed()` is
 * the only path that writes `highlights` state, and it always filters
 * `cacheRef.current` by `paramsRef.current.sectionId` — the CURRENT section,
 * not whatever section a callback closed over when it started. That is what
 * makes an async continuation (a mutation's response, a load) that resolves
 * after the parent has already re-rendered with new params land on (or be
 * dropped by) the right target instead of corrupting whatever is currently
 * displayed.
 *
 * Mutations follow the repo's optimistic-update convention: update local
 * state immediately, then reconcile with the server response; on failure,
 * roll back just the affected row and surface `error` via describeError.
 * `createFromSelector` is the one exception — there is no local id to
 * optimistically render before the POST returns one, so it appends only
 * once the server confirms (per the task interface).
 *
 * Every returned callback is wrapped in useCallback (CLAUDE.md's
 * Chat.js/loadHistory rule) so consumers' effects don't thrash.
 */
export function useHighlights(courseId: string, sectionId: string): UseHighlights {
  const [highlights, setHighlights] = useState<HighlightOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const cacheRef = useRef<HighlightOut[]>([]);
  const paramsRef = useRef<Params>({ courseId, sectionId });

  useEffect(() => {
    paramsRef.current = { courseId, sectionId };
  }, [courseId, sectionId]);

  const syncDisplayed = useCallback(() => {
    setHighlights(cacheRef.current.filter((h) => h.section_id === paramsRef.current.sectionId));
  }, []);

  useEffect(() => {
    let active = true;
    fetchHighlights(courseId).then((result) => {
      if (!active) return;
      if (!result.ok) {
        setError(result.error);
        return;
      }
      // The course may have changed again before this resolved — an
      // in-flight load for an old course must never clobber the cache of
      // whatever course is current now.
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
    fetchHighlights(requestedCourseId).then((result) => {
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

  const createFromSelector = useCallback(
    async (
      sel: QuoteSelector,
      color: HighlightColor,
      page: number | null,
      surface: "source" | "pdf",
    ): Promise<HighlightOut | null> => {
      const body: HighlightIn = {
        section_id: sectionId,
        exact: sel.exact,
        prefix: sel.prefix,
        suffix: sel.suffix,
        occurrence: sel.occurrence,
        page,
        color,
        surface,
      };
      const { data, status, ok } = await createHighlight(courseId, body);
      if (!ok || !data) {
        setError(describeError(status, "Creating highlight").message);
        return null;
      }
      setError(null);
      cacheRef.current = [...cacheRef.current, data];
      syncDisplayed();
      return data;
    },
    [courseId, sectionId, syncDisplayed],
  );

  const updateOne = useCallback(
    async (id: string, patch: HighlightUpdateIn): Promise<void> => {
      const original = cacheRef.current.find((h) => h.id === id);
      if (!original) return;

      // HighlightUpdateIn's `color` is typed nullable (it shares the
      // Optional[...] shape with note_md server-side) even though clearing
      // a highlight's color isn't a real operation — a plain `{...original,
      // ...patch}` spread would let a `null` color widen HighlightOut.color
      // past its non-null enum, so only known-defined fields get applied.
      const optimistic: HighlightOut = {
        ...original,
        ...(patch.color != null ? { color: patch.color } : {}),
        ...(patch.note_md !== undefined ? { note_md: patch.note_md } : {}),
      };
      cacheRef.current = cacheRef.current.map((h) => (h.id === id ? optimistic : h));
      setError(null);
      syncDisplayed();

      const { data, status, ok } = await updateHighlight(id, patch);
      if (!ok || !data) {
        cacheRef.current = cacheRef.current.map((h) => (h.id === id ? original : h));
        setError(describeError(status, "Updating highlight").message);
        syncDisplayed();
        return;
      }
      cacheRef.current = cacheRef.current.map((h) => (h.id === id ? data : h));
      syncDisplayed();
    },
    [syncDisplayed],
  );

  const deleteOne = useCallback(
    async (id: string): Promise<void> => {
      const index = cacheRef.current.findIndex((h) => h.id === id);
      if (index === -1) return;
      const original = cacheRef.current[index];
      cacheRef.current = cacheRef.current.filter((h) => h.id !== id);
      setError(null);
      syncDisplayed();

      const { ok, status } = await deleteHighlight(id);
      if (!ok) {
        // Re-insert at its original position rather than appending, so a
        // failed delete doesn't reorder the list out from under the user.
        const restored = [...cacheRef.current];
        restored.splice(index, 0, original);
        cacheRef.current = restored;
        setError(describeError(status, "Deleting highlight").message);
        syncDisplayed();
      }
    },
    [syncDisplayed],
  );

  return { highlights, error, createFromSelector, updateOne, deleteOne, reload };
}
