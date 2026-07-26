"use client";

import Link from "next/link";
import { useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import Badge from "@/components/ui/Badge";
import Card from "@/components/ui/Card";
import EmptyState from "@/components/ui/EmptyState";
import ProgressBar from "@/components/ui/ProgressBar";
import Skeleton from "@/components/ui/Skeleton";
import { useSkillMap } from "@/lib/hooks/useSkillMap";
import { blockedBy, describeNode, rootCause } from "@/lib/skills/derive";

import { STATUS_BADGE_TONE, STATUS_BAR_TONE, STATUS_LABEL, joinNames, type SkillStatus } from "./format";
import { computeSkillMapLayout } from "./layout";
import LinkButton from "./LinkButton";
import { useCourseTitle } from "./useCourseTitle";

export interface SkillMapViewProps {
  courseId: string;
}

/**
 * Per-course skill map (design handoff §7) — reads the real competency
 * graph via GET /api/courses/{course_id}/skills. Only the course title and
 * the skill map are separate fetches (useCourseTitle / useSkillMap); the
 * layout/root-cause/blocked-by math below is all derived client-side from
 * whichever resolves.
 */
export default function SkillMapView({ courseId }: SkillMapViewProps) {
  const { title: courseTitle, error: titleError, reload: reloadTitle } = useCourseTitle(courseId);
  const { map, error: mapError, reload: reloadMap } = useSkillMap(courseId);

  const error = titleError ?? mapError;
  if (error) {
    return (
      <div className="mx-auto w-full max-w-[1100px] px-9 py-8">
        <ErrorBanner
          status={error.status}
          message={error.message}
          onRetry={titleError ? reloadTitle : reloadMap}
        />
      </div>
    );
  }

  if (courseTitle === null || map === null) {
    return (
      <div className="mx-auto flex w-full max-w-[1100px] flex-col gap-4 px-9 py-8">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-9 w-96" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  const { nodes, edges } = map;

  if (nodes.length === 0) {
    return (
      <div className="mx-auto w-full max-w-[1100px] px-9 py-8">
        <EmptyState
          icon="🧭"
          title="No skill graph yet"
          body="Run backend/prompts/v1/prereq_extraction.md against this course and import the JSON via PUT /api/courses/{id}/skills/graph"
        />
      </div>
    );
  }

  const layout = computeSkillMapLayout(nodes, edges);
  const fix = rootCause(nodes, edges);
  const fixBlocked = fix ? blockedBy(nodes, edges, fix.prereq.id) : [];

  return (
    <div className="mx-auto flex w-full max-w-[1100px] flex-col gap-6 px-9 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="mb-1 text-sm font-semibold">
            <Link href={`/course/${courseId}`} className="text-accent-700 hover:underline">
              {courseTitle}
            </Link>
            <span className="text-muted-foreground opacity-60"> / </span>
            <span className="text-muted-foreground">Skill map</span>
          </p>
          <h1 className="text-[34px]">Skill map — {courseTitle}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Built from this course&apos;s chapters, tests and reviews · click a skill to see what
            to review · skills build left to right
          </p>
        </div>
        <MapViewToggle />
      </div>

      <div className="overflow-x-auto pb-2">
        <div className="relative" style={{ width: layout.canvasWidth, height: layout.canvasHeight }}>
          <svg
            width={layout.canvasWidth}
            height={layout.canvasHeight}
            className="pointer-events-none absolute inset-0"
            aria-hidden="true"
          >
            {layout.dividers.map((d) => (
              <line
                key={`divider-${d.x}`}
                x1={d.x}
                y1={18}
                x2={d.x}
                y2={d.y2}
                stroke="var(--color-divider)"
                strokeWidth={1}
              />
            ))}
            {layout.edges.map((e) => (
              <path
                key={`edge-${e.from}-${e.to}`}
                d={e.d}
                fill="none"
                stroke={e.kind === "met" ? "var(--sage-500)" : "var(--accent)"}
                strokeWidth={2.5}
                strokeDasharray={e.kind === "weak" ? "6 5" : undefined}
              />
            ))}
            {layout.edges.map((e) => (
              <circle
                key={`dot-${e.from}-${e.to}`}
                cx={e.tx}
                cy={e.ty}
                r={4}
                fill={e.kind === "met" ? "var(--sage-500)" : "var(--accent)"}
              />
            ))}
          </svg>

          {layout.lanes.map((lane) => (
            <p
              key={lane.level}
              className="absolute top-0 w-[260px] text-[11px] font-bold uppercase tracking-[0.1em] text-neutral-600"
              style={{ left: lane.leftPx }}
            >
              {lane.name}
            </p>
          ))}

          {nodes.map((node) => {
            const pos = layout.nodePositions[node.id];
            if (!pos) return null;
            const status = node.status as SkillStatus;
            return (
              <Link
                key={node.id}
                href={`/course/${courseId}/skills/${node.id}`}
                style={{ left: pos.leftPx, top: pos.topPx }}
                className={`absolute flex h-[118px] w-[260px] flex-col gap-[7px] rounded-lg bg-surface-raised p-[14px_16px] text-foreground shadow-sm transition-[box-shadow,translate] hover:-translate-y-px hover:shadow-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${
                  status === "struggling" ? "border-[1.5px] border-accent" : "border border-divider"
                }`}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="text-sm font-bold">{node.label}</span>
                  <Badge tone={STATUS_BADGE_TONE[status]}>{STATUS_LABEL[status]}</Badge>
                </span>
                <ProgressBar
                  percent={node.mastery}
                  label={`${node.label} mastery`}
                  tone={STATUS_BAR_TONE[status]}
                />
                <span className="text-xs text-muted-foreground">{describeNode(node, nodes, edges)}</span>
              </Link>
            );
          })}
        </div>
      </div>

      <div className="flex flex-row gap-6 text-xs text-muted-foreground">
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block h-0 w-[26px] border-t-[2.5px] border-sage-500" />
          prerequisite met
        </span>
        <span className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="inline-block h-0 w-[26px] border-t-[2.5px] border-dashed border-accent"
          />
          weak prerequisite — fix first
        </span>
      </div>

      {fix && (
        <Card className="flex flex-row items-center gap-4 py-5 shadow-md">
          <div className="flex-1">
            <span className="text-xs font-semibold uppercase tracking-wide text-accent-800">
              Recommended fix
            </span>
            <p className="mt-1.5 text-[15px] leading-relaxed">
              <strong>{fix.prereq.label}</strong> is weak and is the root cause blocking{" "}
              <strong>{joinNames(fixBlocked.map((n) => n.label))}</strong>. A focused review of{" "}
              {fix.prereq.label} should unblock {fixBlocked.length > 1 ? "them" : "it"}.
            </p>
          </div>
          <LinkButton href={`/course/${courseId}/skills/${fix.prereq.id}`} variant="primary">
            Start 4-min fix
          </LinkButton>
          <LinkButton href={`/course/${courseId}/skills/${fix.prereq.id}#taught`} variant="secondary">
            See what to review
          </LinkButton>
        </Card>
      )}
    </div>
  );
}

/** "By prerequisite / By chapter" segmented toggle — only the prerequisite
 * view is implemented; by-chapter is optional v2 per the handoff. */
function MapViewToggle() {
  const [view] = useState<"prerequisite" | "chapter">("prerequisite");

  return (
    <div
      role="group"
      aria-label="Map view"
      className="inline-flex items-center gap-1 rounded-md border border-border bg-surface-raised p-1 text-sm font-medium"
    >
      <button
        type="button"
        aria-pressed={view === "prerequisite"}
        className="rounded-[6px] bg-background px-3 py-1.5 shadow-sm"
      >
        By prerequisite
      </button>
      <button
        type="button"
        disabled
        title="Coming with the competency backend"
        className="rounded-[6px] px-3 py-1.5 text-muted-foreground disabled:cursor-not-allowed disabled:opacity-45"
      >
        By chapter
      </button>
    </div>
  );
}
