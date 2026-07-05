"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import HintRow from "@/components/HintRow";
import ShortcutsOverlay, { type ShortcutHint } from "@/components/ShortcutsOverlay";
import { getSection } from "@/lib/api/client";
import { useKeyboardShortcuts } from "@/lib/hooks/useKeyboardShortcuts";
import { useProgressSync } from "@/lib/hooks/useProgressSync";
import { useTypographyPrefs } from "@/lib/hooks/useTypographyPrefs";
import type { ReaderCourse, ReaderProgress, SectionBodyState } from "@/lib/reader/types";

import type { LessonDisplayStatus } from "./LessonPane";
import ReadingColumn, { type ViewMode } from "./ReadingColumn";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";
import UsageFooter from "./UsageFooter";

const SHORTCUT_HINTS: ShortcutHint[] = [
  { keys: "← / → or j / k", description: "Next / previous chapter" },
  { keys: "s", description: "Toggle source / lesson view" },
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

export default function CourseReader({ course, initialProgress }: CourseReaderProps) {
  const sections = useMemo(
    () => [...course.sections].sort((a, b) => a.order_index - b.order_index),
    [course.sections],
  );

  const [activeIndex, setActiveIndex] = useState(() => {
    if (!initialProgress.section_id) return 0;
    const index = sections.findIndex((section) => section.id === initialProgress.section_id);
    return index === -1 ? 0 : index;
  });
  const [mode, setMode] = useState<ViewMode>("source");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
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

  const activeSection = sections[activeIndex];

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
  // here" is a snap-into-place, not a moment worth animating.
  const hasRestoredScroll = useRef(false);
  useEffect(() => {
    if (hasRestoredScroll.current) return;
    const el = columnRef.current;
    if (!el) return;
    if (sectionBodies[activeSection.id] === undefined) return;
    hasRestoredScroll.current = true;
    const scrollable = el.scrollHeight - el.clientHeight;
    if (scrollable > 0) {
      el.scrollTo({ top: scrollable * initialProgress.scroll_pos, behavior: "auto" });
    }
  }, [sectionBodies, activeSection.id, initialProgress.scroll_pos]);

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
      </div>
      <UsageFooter key={usageRefreshKey} courseId={course.id} />
      <HintRow
        hints={SHORTCUT_HINTS.map((hint) => ({ keys: hint.keys, label: hint.description }))}
      />
      <ShortcutsOverlay open={shortcutsOpen} onClose={closeShortcuts} shortcuts={SHORTCUT_HINTS} />
    </div>
  );
}
