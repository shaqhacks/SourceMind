"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import HintRow from "@/components/HintRow";
import ShortcutsOverlay, { type ShortcutHint } from "@/components/ShortcutsOverlay";
import { isHighlightApiSupported } from "@/lib/annotations/useHighlightPainter";
import {
  getSection,
  listChapters,
  type ChatSelectionIn,
  type HighlightOut,
  type SectionOut,
} from "@/lib/api/client";
import { useChatOpenPref } from "@/lib/hooks/useChatOpenPref";
import { useDialogFocus } from "@/lib/hooks/useDialogFocus";
import { useKeyboardShortcuts } from "@/lib/hooks/useKeyboardShortcuts";
import { useProgressSync } from "@/lib/hooks/useProgressSync";
import { useReaderView } from "@/lib/hooks/useReaderView";
import { useSidebarCollapsed } from "@/lib/hooks/useSidebarCollapsed";
import { useShellLayout } from "@/lib/hooks/useShellLayout";
import { useTypographyPrefs } from "@/lib/hooks/useTypographyPrefs";
import { findNextContentIndex } from "@/lib/reader/chapterNav";
import { chapterGroupKey } from "@/lib/reader/chapterGroups";
import type {
  ChapterTestStats,
  ReaderCourse,
  ReaderProgress,
  SectionBodyState,
  ViewMode,
} from "@/lib/reader/types";
import { nextViewMode } from "@/lib/reader/viewMode";

import CourseChatDrawer from "./CourseChatDrawer";
import type { LessonDisplayStatus } from "./LessonPane";
import NotesPanel from "./NotesPanel";
import OutlineEditorModal from "./OutlineEditorModal";
import ReadingColumn, { type ExplainSelection } from "./ReadingColumn";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";
import UsageFooter from "./UsageFooter";

const SHORTCUT_HINTS: ShortcutHint[] = [
  { keys: "← / → or j / k", description: "Next / previous chapter" },
  { keys: "s", description: "Cycle source / pages / lesson view" },
  { keys: "c", description: "Toggle chat" },
  { keys: "o", description: "Edit outline" },
  { keys: "?", description: "Show this help" },
];

export interface CourseReaderProps {
  course: ReaderCourse;
  initialProgress: ReaderProgress;
}

function describeBodyError(status: number | undefined): string {
  return status === undefined
    ? "Could not reach the API. Is the backend running?"
    : `Loading chapter failed (HTTP ${status}).`;
}

// getElementById (not querySelector(hash)) deliberately — rehype-slug ids
// can start with a digit (a heading like "1. Introduction" slugifies to
// "1-introduction"), which is a syntax error as a CSS id selector unless
// escaped. contains() scopes the match to this section's own content, not
// some unrelated element elsewhere on the page that happens to share the
// id.
function findHashTarget(container: HTMLElement, hash: string): HTMLElement | null {
  const id = hash.startsWith("#") ? hash.slice(1) : hash;
  if (!id) return null;
  const target = document.getElementById(id);
  return target && container.contains(target) ? target : null;
}

function scrollElementIntoView(el: HTMLElement): void {
  const reducedMotion =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
}

function hasPdfPageProvenance(section: SectionOut | ReaderCourse["sections"][number]): boolean {
  if (section.source_format?.toLowerCase() !== "pdf") return false;
  if (!section.asset_id) return false;
  const pageStart = section.page_start;
  const pageEnd = section.page_end;
  if (typeof pageStart !== "number" || typeof pageEnd !== "number") return false;
  if (!Number.isInteger(pageStart) || !Number.isInteger(pageEnd)) return false;
  return pageStart > 0 && pageEnd >= pageStart;
}

export default function CourseReader({ course, initialProgress }: CourseReaderProps) {
  // Patched wholesale after an outline edit applies (rename/reorder/
  // delete/merge/split) — editOutline's response is the fresh source of
  // truth for the whole list, so this replaces rather than merges into
  // course.sections (a prop, and otherwise immutable for this component's
  // lifetime).
  const [sectionsOverride, setSectionsOverride] = useState<SectionOut[] | null>(null);
  const sections = useMemo(
    () => [...(sectionsOverride ?? course.sections)].sort((a, b) => a.order_index - b.order_index),
    [sectionsOverride, course.sections],
  );

  const [activeIndex, setActiveIndex] = useState(() => {
    if (!initialProgress.section_id) return 0;
    const index = sections.findIndex((section) => section.id === initialProgress.section_id);
    return index === -1 ? 0 : index;
  });
  const { storedMode, setStoredMode } = useReaderView(course.id);
  const { collapsed: sidebarCollapsed, toggle: toggleSidebar } = useSidebarCollapsed();
  const shellLayout = useShellLayout();
  const transientReaderChrome = shellLayout !== "desktop";
  const [outlineOpen, setOutlineOpen] = useState(false);
  const outlineModalOpen = outlineOpen && transientReaderChrome;
  const outlineShellRef = useRef<HTMLDivElement>(null);
  const outlineDialogRef = useDialogFocus<HTMLDivElement>(outlineModalOpen);
  const { open: chatOpen, setOpen: setChatOpen, toggle: toggleChatOpen } = useChatOpenPref(
    course.id,
  );
  // Plain useState (not a per-course pref like chat's) — the notes panel is
  // a glance-and-dismiss list, not a preference worth persisting across
  // sessions. Mutually exclusive with chat (see toggleChat/toggleNotes
  // below): both are right-side slide-overs, and letting both be open at
  // once would either overlap (narrow viewport) or needlessly squeeze the
  // reading column (docked chat) for no benefit — simplest is one slot,
  // shared.
  const [notesOpen, setNotesOpen] = useState(false);
  // Global Constraint: when the CSS Custom Highlight API isn't supported, ALL
  // annotation UI is hidden — including Notes, which is nothing but a list
  // of highlights nobody on this browser can ever create. Computed once
  // (browser support doesn't change mid-session, same rationale as
  // useHighlightPainter's own module-level `supported` flag) and passed down
  // to gate both the TopBar toggle button and the panel itself, rather than
  // each of them calling the detector independently.
  const notesSupported = useMemo(() => isHighlightApiSupported(), []);
  // Set when "Explain" fires on a selection/highlight (ReadingColumn's
  // ExplainSelection, camelCase) and mapped to the wire-shaped
  // ChatSelectionIn (snake_case) right here — the one bridge point between
  // this component's internal naming and the backend schema. Carried into
  // CourseChatDrawer, which attaches it to the next sendChat call and then
  // calls onConsumeSelection (consumeSelection below) to clear it.
  const [pendingSelection, setPendingSelection] = useState<ChatSelectionIn | null>(null);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [outlineEditorOpen, setOutlineEditorOpen] = useState(false);
  const [chapterStats, setChapterStats] = useState<Record<string, ChapterTestStats>>({});
  const [sectionBodies, setSectionBodies] = useState<Record<string, string>>({});
  const [bodyErrors, setBodyErrors] = useState<Record<string, string>>({});
  const [lessonStatusOverrides, setLessonStatusOverrides] = useState<
    Record<string, LessonDisplayStatus>
  >({});
  // Bumped on every settled generation so UsageFooter (keyed on this)
  // remounts and refetches — usage numbers only ever change then, so this
  // is simpler than polling.
  const [usageRefreshKey, setUsageRefreshKey] = useState(0);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const columnRef = useRef<HTMLDivElement>(null);
  const sectionBodiesRef = useRef(sectionBodies);
  useEffect(() => {
    sectionBodiesRef.current = sectionBodies;
  }, [sectionBodies]);
  const typography = useTypographyPrefs();

  // An outline edit can shrink or reorder the section list out from under
  // a still-in-range-looking `activeIndex` (a delete/merge near or before
  // it) — clamped here at read time rather than "corrected" back into
  // state via an effect, so `sections[safeActiveIndex]` is never
  // undefined. `activeIndex` itself is left as whatever the user last
  // navigated to; it self-heals on the next arrow/j/k navigation via
  // goToOffset's own clamp regardless.
  const safeActiveIndex = Math.min(activeIndex, Math.max(sections.length - 1, 0));
  const activeSection = sections[safeActiveIndex];

  // "pages" (the original PDF via pdf.js) needs PDF page provenance on
  // the active section. A stored "pages" preference for a text/HTML/Markdown
  // course degrades to Source instead of opening an empty PDF pane.
  const pagesAvailable = hasPdfPageProvenance(activeSection);
  const mode: ViewMode = storedMode === "pages" && !pagesAvailable ? "source" : storedMode;

  useProgressSync(course.id, activeSection.id, columnRef);

  // Lazily fetch the active section's body the first time it's viewed:
  // list_sections deliberately omits body_md (can be large), so each
  // chapter's text arrives via its own get_section call, cached here for
  // the life of the reader so re-visiting a chapter doesn't re-fetch.
  // Depends only on activeSection.id (not sectionBodies) — the cache
  // itself is read live via the ref so a fetch already in flight for this
  // id doesn't restart every time the cache updates.
  useEffect(() => {
    const id = activeSection.id;
    if (sectionBodiesRef.current[id] !== undefined) return undefined;
    let active = true;
    getSection(id).then(({ data, status }) => {
      if (!active) return;
      if (data) {
        setSectionBodies((prev) => ({ ...prev, [id]: data.body_md }));
      } else {
        setBodyErrors((prev) => ({ ...prev, [id]: describeBodyError(status) }));
      }
    });
    return () => {
      active = false;
    };
  }, [activeSection.id]);

  // Feeds Sidebar's per-chapter "Test" score. Mount-only: an outline edit
  // (rename/merge/split) already refreshes `sections` via its own
  // onApplied callback, and taking a chapter test navigates away to a
  // different route entirely — this component remounts fresh either way,
  // so there's no in-place staleness window this needs to react to.
  useEffect(() => {
    let active = true;
    listChapters(course.id).then(({ data }) => {
      if (!active || !data) return;
      const stats: Record<string, ChapterTestStats> = {};
      for (const chapter of data) {
        if (chapter.test_stats) {
          stats[chapterGroupKey(chapter.chapter_label)] = chapter.test_stats;
        }
      }
      setChapterStats(stats);
    });
    return () => {
      active = false;
    };
  }, [course.id]);

  // Resume: jump to the saved scroll position once, instantly, as soon as
  // the resumed section's body has actually rendered (scrollHeight isn't
  // meaningful before that). Never smooth-scrolled — restoring "you are
  // here" is a snap-into-place, not a moment worth animating. A deep-link
  // hash in the URL (e.g. from a shared link, landing before the target
  // heading even exists in the DOM) takes priority over the saved
  // position — same one-time guard either way, so the two never both
  // fire for the same mount.
  // Known limitation: sectionBodies readiness (the source-text fetch,
  // which always runs regardless of view mode) is a reliable proxy for
  // "the column has real content, scrollHeight is meaningful" for the
  // common case, but view mode now persists across mounts (see
  // useReaderView) — resuming straight into "pages" means this can fire
  // before PdfPagesView's own independent PDF load has painted anything
  // with real height, so `scrollable` reads as 0 and the restore silently
  // no-ops (same as genuinely short content always has). A retry-until-
  // ready loop was tried and reverted: it can fire on a later frame after
  // the user has already scrolled elsewhere, stomping their new position
  // with the stale initial one — worse than the rare miss it fixed.
  const hasRestoredScroll = useRef(false);
  useEffect(() => {
    if (hasRestoredScroll.current) return;
    const el = columnRef.current;
    if (!el) return;
    if (sectionBodies[activeSection.id] === undefined) return;
    hasRestoredScroll.current = true;

    const hash = window.location.hash;
    const hashTarget = hash ? findHashTarget(el, hash) : null;
    if (hashTarget) {
      scrollElementIntoView(hashTarget);
      return;
    }

    const scrollable = el.scrollHeight - el.clientHeight;
    if (scrollable > 0) {
      el.scrollTo({ top: scrollable * initialProgress.scroll_pos, behavior: "auto" });
    }
  }, [sectionBodies, activeSection.id, initialProgress.scroll_pos]);

  // Anchor-link clicks within the column (e.g. a heading's "#" permalink)
  // change location.hash without a route change. The browser's own
  // hash-navigation scroll doesn't reliably reach into a nested
  // overflow-y-auto container in every browser, so handle it explicitly
  // — this is the general, always-on counterpart to the one-time
  // deep-link check above.
  useEffect(() => {
    function handleHashChange() {
      const el = columnRef.current;
      const hash = window.location.hash;
      if (!el || !hash) return;
      const target = findHashTarget(el, hash);
      if (target) scrollElementIntoView(target);
    }
    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, []);

  // Keyboard nav (j/k/arrows) and the reading column's prev/next chevrons
  // both walk content sections only — practice/answers sections are
  // reachable by deep link but aren't part of the reading flow's "next
  // chapter" (their home is the chapter test page). If the direction runs
  // off the end without finding one, stays put rather than landing on a
  // non-content section — the "clamp instead of wrap" behavior
  // generalizes to "clamp instead of landing off-flow".
  const goToOffset = useCallback(
    (offset: number) => {
      const direction = offset > 0 ? 1 : -1;
      setActiveIndex((current) => findNextContentIndex(sections, current, direction) ?? current);
    },
    [sections],
  );

  const goNext = useCallback(() => goToOffset(1), [goToOffset]);
  const goPrevious = useCallback(() => goToOffset(-1), [goToOffset]);
  const toggleOutline = useCallback(() => {
    if (transientReaderChrome) {
      if (outlineOpen) {
        setOutlineOpen(false);
      } else {
        setChatOpen(false);
        setNotesOpen(false);
        setShortcutsOpen(false);
        setOutlineEditorOpen(false);
        setOutlineOpen(true);
      }
      return;
    }
    toggleSidebar();
  }, [outlineOpen, setChatOpen, transientReaderChrome, toggleSidebar]);
  const closeOutline = useCallback(() => setOutlineOpen(false), []);

  useEffect(() => {
    if (!outlineModalOpen) return undefined;

    function handlePointerDown(event: PointerEvent) {
      if (
        outlineShellRef.current &&
        !outlineShellRef.current.contains(event.target as Node)
      ) {
        closeOutline();
      }
    }

    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [outlineModalOpen, closeOutline]);

  // Direct id-based navigation (as opposed to goToOffset's relative
  // stepping) — the same id->index resolution `activeIndex`'s own useState
  // initializer already does for a resumed/deep-linked section_id above,
  // generalized into a callback so NotesPanel (and any other id-based
  // navigation source) can jump straight to a section. A miss (id no
  // longer exists — outline edit) is a no-op rather than clamping to
  // something arbitrary.
  const goToSection = useCallback(
    (sectionId: string) => {
      const index = sections.findIndex((section) => section.id === sectionId);
      if (index !== -1) setActiveIndex(index);
    },
    [sections],
  );

  // Chevron visibility/labels: whether a next/previous content section
  // actually exists from here, and what it's titled — null means "don't
  // render that chevron at all" (matches the clamp above: nothing to
  // navigate to in that direction).
  const nextSection = useMemo(() => {
    const index = findNextContentIndex(sections, safeActiveIndex, 1);
    return index === null ? null : sections[index];
  }, [sections, safeActiveIndex]);
  const previousSection = useMemo(() => {
    const index = findNextContentIndex(sections, safeActiveIndex, -1);
    return index === null ? null : sections[index];
  }, [sections, safeActiveIndex]);
  const cycleMode = useCallback(() => {
    setStoredMode(nextViewMode(mode, pagesAvailable));
  }, [mode, pagesAvailable, setStoredMode]);
  const openShortcuts = useCallback(() => setShortcutsOpen(true), []);
  const closeShortcuts = useCallback(() => setShortcutsOpen(false), []);
  // Mutually exclusive with notes: toggling chat always closes notes first
  // (a no-op if it's already closed) rather than branching on direction —
  // simpler, and harmless either way. NOT symmetric with toggleNotes below:
  // that one only flips notesOpen and deliberately leaves the persisted
  // chat pref alone (see its comment) — chatRenderedOpen is what hides the
  // chat drawer while notes is open.
  const toggleChat = useCallback(() => {
    setNotesOpen(false);
    toggleChatOpen();
  }, [toggleChatOpen]);
  const closeChat = useCallback(() => setChatOpen(false), [setChatOpen]);
  // Deliberately does NOT touch the persisted chat pref (setChatOpen) —
  // chatOpen is a cross-session preference (see useChatOpenPref), and
  // opening Notes is a transient view choice, not the user closing chat.
  // Mutual exclusion with chat is handled purely at render time via
  // chatRenderedOpen below, so the persisted pref survives a Notes visit
  // untouched.
  const toggleNotes = useCallback(() => {
    setNotesOpen((open) => !open);
  }, []);
  const closeNotes = useCallback(() => setNotesOpen(false), []);
  // Clicking a note in NotesPanel both navigates AND dismisses the panel —
  // "go read that highlight" is the whole point of the click, so there's no
  // reason to leave the list open covering the section it just jumped to.
  // A `surface:"pdf"` note additionally forces the view into "pages" — a
  // PDF highlight is painted only there (useHighlightPainter's surface
  // filter), so landing on the section in Source view would jump to the
  // right chapter but show no trace of the highlight the user just clicked.
  // A `surface:"source"` note leaves the current mode alone: it already
  // renders in whatever view the reader is in (Source or Lesson), so there's
  // nothing to switch.
  const handleNotesNavigate = useCallback(
    (sectionId: string, surface: HighlightOut["surface"]) => {
      goToSection(sectionId);
      const target = sections.find((section) => section.id === sectionId);
      if (surface === "pdf" && target && hasPdfPageProvenance(target)) setStoredMode("pages");
      closeNotes();
    },
    [goToSection, sections, setStoredMode, closeNotes],
  );
  const openOutlineEditor = useCallback(() => setOutlineEditorOpen(true), []);
  const closeOutlineEditor = useCallback(() => setOutlineEditorOpen(false), []);
  // "Explain" (SelectionPopover or HighlightEditPopover, via ReadingColumn)
  // maps camelCase -> snake_case into pendingSelection, closes Notes so the
  // mutual-exclusion render (chatRenderedOpen) actually shows the drawer,
  // and opens it.
  const handleExplainSelection = useCallback(
    (sel: ExplainSelection) => {
      setPendingSelection({ section_id: sel.sectionId, exact: sel.exact });
      setNotesOpen(false);
      setChatOpen(true);
    },
    [setChatOpen],
  );
  // Clears only if `sent` (the selection CourseChatDrawer actually attached
  // to the just-settled send/removal) is still the current pendingSelection.
  // Without the identity check, a selection attached while an earlier send
  // was in flight would get nulled out the moment that earlier send's
  // onConsumeSelection callback fires, even though it was never sent yet.
  const consumeSelection = useCallback(
    (sent: ChatSelectionIn) => setPendingSelection((current) => (current === sent ? null : current)),
    [],
  );
  const handleOutlineApplied = useCallback((updated: SectionOut[]) => {
    setSectionsOverride(updated);
  }, []);

  // Sidebar shows list_sections' lesson_status, which goes stale the
  // moment a generation (single or part of "generate all") completes for
  // that section. This overlay is how both LessonPane (the active
  // section) and GenerateAllLessons (any section in a batch) patch just
  // the one field that changed, without a full course refetch.
  const patchLessonStatus = useCallback((sectionId: string, status: LessonDisplayStatus) => {
    setLessonStatusOverrides((prev) =>
      prev[sectionId] === status ? prev : { ...prev, [sectionId]: status },
    );
    // A settled generation is the only thing that changes usage numbers.
    // LessonPane/GenerateAllLessons only call this on an actual status
    // change, so this doesn't fire on every render.
    if (status === "ready" || status === "failed") {
      setUsageRefreshKey((key) => key + 1);
    }
  }, []);

  useKeyboardShortcuts({
    arrowright: goNext,
    j: goNext,
    arrowleft: goPrevious,
    k: goPrevious,
    s: cycleMode,
    c: toggleChat,
    o: openOutlineEditor,
    "?": openShortcuts,
  }, !outlineModalOpen);
  useKeyboardShortcuts({ escape: closeOutline }, outlineModalOpen);

  // Focus the chapter heading itself, not a state setter — a DOM
  // side-effect synchronizing with the (uncontrolled) focus system, which
  // is exactly what an effect is for.
  useEffect(() => {
    headingRef.current?.focus();
  }, [activeIndex]);

  // What CourseChatDrawer actually renders: chatOpen is the persisted
  // cross-session pref (see useChatOpenPref / toggleNotes above), which
  // must survive a Notes visit untouched. This derived value is what
  // implements the mutual-exclusion visually — Notes hides chat without
  // ever writing to the pref — and is intentionally NOT what TopBar's
  // Chat button reflects (that button shows toggle *intent*, i.e. the
  // persisted pref, not momentary visibility).
  const chatRenderedOpen = chatOpen && !notesOpen;

  const bodyState: SectionBodyState =
    sectionBodies[activeSection.id] !== undefined
      ? { kind: "ready", body: sectionBodies[activeSection.id] }
      : bodyErrors[activeSection.id] !== undefined
        ? { kind: "error", message: bodyErrors[activeSection.id] }
        : { kind: "loading" };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <TopBar
        courseId={course.id}
        courseTitle={course.title}
        chapterLabel={activeSection.chapter_label}
        sectionTitle={activeSection.title}
        sidebarCollapsed={transientReaderChrome ? !outlineOpen : sidebarCollapsed}
        onToggleSidebar={toggleOutline}
        onLessonSectionSettled={patchLessonStatus}
        chatOpen={chatOpen}
        onToggleChat={toggleChat}
        notesSupported={notesSupported}
        notesOpen={notesOpen}
        onToggleNotes={toggleNotes}
        onOpenOutlineEditor={openOutlineEditor}
        viewMode={mode}
        pagesAvailable={pagesAvailable}
        onChangeViewMode={setStoredMode}
      />
      <div className="flex min-h-0 flex-1">
        {!transientReaderChrome && !sidebarCollapsed && (
          <Sidebar
            courseId={course.id}
            sections={sections}
            activeSectionId={activeSection.id}
            onSelect={setActiveIndex}
            lessonStatusOverrides={lessonStatusOverrides}
            chapterStats={chapterStats}
          />
        )}
        {outlineModalOpen && (
          <div className="fixed inset-0 z-40 bg-foreground/25">
            <div
              ref={outlineShellRef}
              role="dialog"
              aria-modal="true"
              aria-label="Chapter outline"
              data-layout={shellLayout}
              className="h-full w-[min(22rem,88vw)] border-r border-divider bg-background shadow-lg"
            >
              <div ref={outlineDialogRef} tabIndex={-1} className="flex h-full flex-col">
                <div className="flex items-center justify-between gap-3 border-b border-divider px-4 py-3">
                  <p className="text-sm font-semibold uppercase tracking-[0.06em] text-muted-foreground">
                    Outline
                  </p>
                  <button
                    type="button"
                    onClick={closeOutline}
                    aria-label="Close outline"
                    className="min-h-11 rounded-md border border-border bg-surface-raised px-3 py-2 text-sm font-medium transition-colors hover:bg-foreground/[0.07]"
                  >
                    Close
                  </button>
                </div>
                <Sidebar
                  courseId={course.id}
                  sections={sections}
                  activeSectionId={activeSection.id}
                  onSelect={(index) => {
                    setActiveIndex(index);
                    closeOutline();
                  }}
                  lessonStatusOverrides={lessonStatusOverrides}
                  chapterStats={chapterStats}
                />
              </div>
            </div>
          </div>
        )}
        <ReadingColumn
          key={activeSection.id}
          courseId={course.id}
          section={activeSection}
          mode={mode}
          typography={typography.prefs}
          headingRef={headingRef}
          columnRef={columnRef}
          body={bodyState}
          onLessonStatusChange={patchLessonStatus}
          onNext={goNext}
          onPrevious={goPrevious}
          nextTitle={nextSection?.title ?? null}
          previousTitle={previousSection?.title ?? null}
          onExplainSelection={handleExplainSelection}
        />
        <CourseChatDrawer
          courseId={course.id}
          open={chatRenderedOpen}
          onClose={closeChat}
          pendingSelection={pendingSelection}
          onConsumeSelection={consumeSelection}
        />
        {notesSupported && (
          <NotesPanel
            courseId={course.id}
            open={notesOpen}
            sections={sections}
            onClose={closeNotes}
            onNavigate={handleNotesNavigate}
          />
        )}
      </div>
      <UsageFooter key={usageRefreshKey} courseId={course.id} />
      <HintRow
        hints={SHORTCUT_HINTS.map((hint) => ({ keys: hint.keys, label: hint.description }))}
      />
      <ShortcutsOverlay open={shortcutsOpen} onClose={closeShortcuts} shortcuts={SHORTCUT_HINTS} />
      <OutlineEditorModal
        courseId={course.id}
        open={outlineEditorOpen}
        onClose={closeOutlineEditor}
        onApplied={handleOutlineApplied}
      />
    </div>
  );
}
