"use client";

import { useEffect, useRef, useState } from "react";
import type { DragEvent } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  getLlmUsage,
  getReviewSummary,
  listCourses,
  type CourseOut,
  type LlmUsageOut,
  type ReviewSummaryOut,
} from "@/lib/api/client";
import { subscribeReviewSettled } from "@/lib/review/reviewBus";
import { useSidebarCollapsed } from "@/lib/hooks/useSidebarCollapsed";
import UploadFlow from "@/components/upload/UploadFlow";

const NAV_ITEMS: { href: string; label: string }[] = [
  { href: "/", label: "Home" },
  { href: "/flashcards", label: "Flashcards" },
  { href: "/tests", label: "Tests" },
  { href: "/jobs", label: "Jobs" },
  { href: "/settings", label: "Settings" },
];

function isPdf(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

/**
 * Collapsible app sidebar (redesign handoff "App Shell"): primary
 * "Start new course" action, top-level nav, per-course cards with
 * Open / Skill map sub-links, and the LLM-usage footer. Data refetches
 * on route change and on the review bus, mirroring DueBadge — no polling.
 *
 * Deviation from the mock: no per-course progress bar — CourseOut carries
 * no percent and deriving one costs a listSections call per course on
 * every mount of an always-visible panel. The Home task cards carry the
 * detailed progress instead.
 */
export default function AppSidebar() {
  const pathname = usePathname();
  const { collapsed } = useSidebarCollapsed();
  const [courses, setCourses] = useState<CourseOut[]>([]);
  const [summary, setSummary] = useState<ReviewSummaryOut | null>(null);
  const [usage, setUsage] = useState<LlmUsageOut | null>(null);
  const [pendingFiles, setPendingFiles] = useState<File[] | null>(null);
  const [dropActive, setDropActive] = useState(false);
  const dragDepth = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function handleFilesChosen(chosen: FileList | File[]) {
    const pdfs = Array.from(chosen).filter(isPdf);
    if (pdfs.length > 0) setPendingFiles(pdfs);
  }

  function handleDropZoneDragEnter(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    dragDepth.current += 1;
    if (event.dataTransfer.types.includes("Files")) setDropActive(true);
  }

  function handleDropZoneDragLeave(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    dragDepth.current -= 1;
    if (dragDepth.current <= 0) {
      dragDepth.current = 0;
      setDropActive(false);
    }
  }

  function handleDropZoneDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
  }

  function handleDropZoneDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    dragDepth.current = 0;
    setDropActive(false);
    handleFilesChosen(event.dataTransfer.files);
  }

  useEffect(() => {
    let active = true;
    listCourses().then(({ data }) => {
      if (active && data) setCourses(data);
    });
    getReviewSummary().then(({ data }) => {
      if (active && data) setSummary(data);
    });
    getLlmUsage().then(({ data }) => {
      if (active && data) setUsage(data);
    });
    return () => {
      active = false;
    };
  }, [pathname]);

  useEffect(() => {
    let active = true;
    const unsubscribe = subscribeReviewSettled(() => {
      getReviewSummary().then(({ data }) => {
        if (active && data) setSummary(data);
      });
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);

  if (collapsed) return null;

  const dueByCourse = new Map(
    (summary?.courses ?? []).map((c) => [c.course_id, c.due_count]),
  );

  return (
    <nav
      id="app-sidebar"
      aria-label="App"
      className="flex w-[260px] flex-none flex-col gap-5 overflow-y-auto border-r border-divider p-4"
    >
      <input
        ref={fileInputRef}
        type="file"
        accept="application/pdf"
        multiple
        className="hidden"
        aria-label="Upload course PDF"
        onChange={(event) => {
          if (event.target.files) handleFilesChosen(event.target.files);
          event.target.value = "";
        }}
      />
      <button
        type="button"
        onClick={() => fileInputRef.current?.click()}
        className="block w-full rounded-md bg-accent-700 px-4 py-2 text-center font-heading text-sm text-background transition-colors hover:bg-accent-800"
      >
        + Start new course
      </button>

      <ul className="flex flex-col gap-1">
        {NAV_ITEMS.map((item) => {
          const active =
            item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`flex items-center justify-between rounded-md px-3.5 py-2 text-sm transition-colors ${
                  active
                    ? "bg-surface-raised font-semibold text-accent-700 shadow-sm"
                    : "hover:bg-foreground/[0.07]"
                }`}
              >
                {item.label}
                {item.href === "/flashcards" && summary && summary.due_total > 0 ? (
                  <span className="rounded-[6px] bg-accent-soft px-2 py-0.5 text-xs font-semibold text-accent-800">
                    {summary.due_total}
                  </span>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>

      <div className="flex flex-col gap-2">
        <p className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
          Your courses
        </p>
        {courses.map((course) => {
          const due = dueByCourse.get(course.id) ?? 0;
          return (
            <div
              key={course.id}
              className="flex flex-col gap-1 rounded-lg border border-divider bg-surface-raised p-3"
            >
              <Link
                href={`/course/${course.id}`}
                className="text-sm font-semibold hover:text-accent-700"
              >
                {course.title}
              </Link>
              <p className="text-xs text-muted-foreground">
                {course.section_count} section{course.section_count === 1 ? "" : "s"}
                {due > 0 ? ` · ${due} due` : ""}
              </p>
              <p className="flex gap-2 text-xs">
                <Link href={`/course/${course.id}`} className="text-accent-700 hover:underline">
                  Open
                </Link>
                <span aria-hidden="true" className="text-muted-foreground">
                  ·
                </span>
                <Link
                  href={`/course/${course.id}/skills`}
                  className="text-accent-700 hover:underline"
                >
                  Skill map
                </Link>
                <span aria-hidden="true" className="text-muted-foreground">·</span>
                <Link href={`/course/${course.id}/curriculum`} className="text-accent-700 hover:underline">
                  Curriculum
                </Link>
                <span aria-hidden="true" className="text-muted-foreground">·</span>
                <Link href={`/course/${course.id}/diagnostics/validate`} className="text-accent-700 hover:underline">
                  Validate
                </Link>
              </p>
            </div>
          );
        })}
        <div
          onDragEnter={handleDropZoneDragEnter}
          onDragLeave={handleDropZoneDragLeave}
          onDragOver={handleDropZoneDragOver}
          onDrop={handleDropZoneDrop}
          className={`rounded-lg border border-dashed p-3 text-center text-xs transition-colors ${
            dropActive
              ? "border-accent text-accent-700"
              : "border-border text-muted-foreground hover:border-accent hover:text-accent-700"
          }`}
        >
          Drop a PDF here to add one
        </div>
      </div>

      {usage ? (
        <p className="mt-auto border-t border-divider pt-3 text-xs text-muted-foreground">
          LLM usage: {usage.calls} call{usage.calls === 1 ? "" : "s"} · $
          {usage.est_cost_usd.toFixed(2)}
        </p>
      ) : null}

      {pendingFiles && (
        <UploadFlow files={pendingFiles} onClose={() => setPendingFiles(null)} />
      )}
    </nav>
  );
}
