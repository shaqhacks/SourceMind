"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import HintRow from "@/components/HintRow";
import ShortcutsOverlay, { type ShortcutHint } from "@/components/ShortcutsOverlay";
import { getSection, type SectionOut } from "@/lib/api/client";
import { useKeyboardShortcuts } from "@/lib/hooks/useKeyboardShortcuts";
import { useProgressSync } from "@/lib/hooks/useProgressSync";
import { useTypographyPrefs } from "@/lib/hooks/useTypographyPrefs";
import type { ReaderCourse, ReaderProgress, SectionBodyState } from "@/lib/reader/types";

import CourseChatDrawer from "./CourseChatDrawer";
import type { LessonDisplayStatus } from "./LessonPane";
import OutlineEditorModal from "./OutlineEditorModal";
import ReadingColumn, { type ViewMode } from "./ReadingColumn";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";
import UsageFooter from "./UsageFooter";

const SHORTCUT_HINTS: ShortcutHint[] = [
  { keys: "← / → or j / k", description: "Next / previous chapter" },
  { keys: "s", description: "Toggle source / lesson view" },
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
  const [mode, setMode] = useState<ViewMode>("source");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [outlineEditorOpen, setOutlineEditorOpen] = useState(false);
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

  // Resume: jump to the saved scroll position once, instantly, as soon as
  // the resumed section's body has actually rendered (scrollHeight isn't
  // meaningful before that). Never smooth-scrolled — restoring "you are
  // here" is a snap-into-place, not a moment worth animating. A deep-link
  // hash in the URL (e.g. from a shared link, landing before the target
  // heading even exists in the DOM) takes priority over the saved
  // position — same one-time guard either way, so the two never both
  // fire for the same mount.
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

  const goToOffset = useCallback(
    (offset: number) => {
      setActiveIndex((current) => {
        const next = current + offset;
        return Math.min(Math.max(next, 0), sections.length - 1);
      });
    },
    [sections.length],
  );

  const goNext = useCallback(() => goToOffset(1), [goToOffset]);
  const goPrevious = useCallback(() => goToOffset(-1), [goToOffset]);
  const toggleMode = useCallback(() => {
    setMode((current) => (current === "source" ? "lesson" : "source"));
  }, []);
  const openShortcuts = useCallback(() => setShortcutsOpen(true), []);
  const closeShortcuts = useCallback(() => setShortcutsOpen(false), []);
  const toggleChat = useCallback(() => setChatOpen((value) => !value), []);
  const closeChat = useCallback(() => setChatOpen(false), []);
  const openOutlineEditor = useCallback(() => setOutlineEditorOpen(true), []);
  const closeOutlineEditor = useCallback(() => setOutlineEditorOpen(false), []);
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
    s: toggleMode,
    c: toggleChat,
    o: openOutlineEditor,
    "?": openShortcuts,
  });

  // Focus the chapter heading itself, not a state setter — a DOM
  // side-effect synchronizing with the (uncontrolled) focus system, which
  // is exactly what an effect is for.
  useEffect(() => {
    headingRef.current?.focus();
  }, [activeIndex]);

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
        sidebarCollapsed={sidebarCollapsed}
        onToggleSidebar={() => setSidebarCollapsed((value) => !value)}
        onLessonSectionSettled={patchLessonStatus}
        chatOpen={chatOpen}
        onToggleChat={toggleChat}
        onOpenOutlineEditor={openOutlineEditor}
      />
      <div className="flex min-h-0 flex-1">
        {!sidebarCollapsed && (
          <Sidebar
            sections={sections}
            activeSectionId={activeSection.id}
            onSelect={setActiveIndex}
            lessonStatusOverrides={lessonStatusOverrides}
          />
        )}
        <ReadingColumn
          section={activeSection}
          mode={mode}
          typography={typography.prefs}
          headingRef={headingRef}
          columnRef={columnRef}
          body={bodyState}
          onLessonStatusChange={patchLessonStatus}
        />
        <CourseChatDrawer courseId={course.id} open={chatOpen} onClose={closeChat} />
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
