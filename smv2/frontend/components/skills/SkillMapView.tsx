"use client";

import Link from "next/link";
import { useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import Badge from "@/components/ui/Badge";
import Card from "@/components/ui/Card";
import EmptyState from "@/components/ui/EmptyState";
import ProgressBar from "@/components/ui/ProgressBar";
import Skeleton from "@/components/ui/Skeleton";
import type { SkillEdgeOut } from "@/lib/api/client";
import { useSkillMap } from "@/lib/hooks/useSkillMap";
import { describeNode, mostNeedsReview } from "@/lib/skills/derive";

import { STATUS_BADGE_TONE, STATUS_BAR_TONE, STATUS_LABEL, type SkillStatus } from "./format";
import { computeSkillMapLayout, SKILL_CARD_HEIGHT, SKILL_CARD_WIDTH } from "./layout";
import LinkButton from "./LinkButton";
import { useCourseTitle } from "./useCourseTitle";

export interface SkillMapViewProps {
  courseId: string;
}

const EDGE_COLOR: Record<SkillEdgeOut["kind"], string> = {
  ready: "var(--sage-500)",
  review_suggested: "var(--accent)",
};

/**
 * Per-course skill map (design handoff §7) — reads the real competency
 * graph via GET /api/courses/{course_id}/skills. Only the course title and
 * the skill map are separate fetches (useCourseTitle / useSkillMap); the
 * layout and display labels are derived client-side from whichever resolves.
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
  const reviewTarget = mostNeedsReview(nodes);

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
                stroke={EDGE_COLOR[e.kind]}
                strokeWidth={2.5}
                strokeDasharray={e.kind === "review_suggested" ? "6 5" : undefined}
              />
            ))}
            {layout.edges.map((e) => (
              <circle
                key={`dot-${e.from}-${e.to}`}
                cx={e.tx}
                cy={e.ty}
                r={4}
                fill={EDGE_COLOR[e.kind]}
              />
            ))}
          </svg>

          {layout.lanes.map((lane) => (
            <p
              key={lane.level}
              className="absolute top-0 text-[11px] font-bold uppercase tracking-[0.1em] text-neutral-600"
              style={{ left: lane.leftPx, width: SKILL_CARD_WIDTH }}
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
                style={{ left: pos.leftPx, top: pos.topPx, width: SKILL_CARD_WIDTH, height: SKILL_CARD_HEIGHT }}
                className={`absolute flex flex-col gap-[7px] rounded-lg bg-surface-raised p-[14px_16px] text-foreground shadow-sm transition-[box-shadow,translate] hover:-translate-y-px hover:shadow-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${
                  status === "likely_struggling"
                    ? "border-[1.5px] border-accent"
                    : "border border-divider"
                }`}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="text-sm font-bold">{node.label}</span>
                  <Badge tone={STATUS_BADGE_TONE[status]}>{STATUS_LABEL[status]}</Badge>
                </span>
                {node.readiness_estimate == null ? (
                  <span className="text-xs text-muted-foreground">Estimate pending more varied practice</span>
                ) : (
                  <ProgressBar
                    percent={Math.round(node.readiness_estimate * 100)}
                    label={`${node.label} readiness`}
                    tone={STATUS_BAR_TONE[status]}
                  />
                )}
                <span className="text-xs text-muted-foreground">{describeNode(node)}</span>
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
          prerequisite review suggested
        </span>
      </div>

      {reviewTarget && (
        <Card className="flex flex-row items-center gap-4 py-5 shadow-md">
          <div className="flex-1">
            <span className="text-xs font-semibold uppercase tracking-wide text-accent-800">
              Recommended review
            </span>
            <p className="mt-1.5 text-[15px] leading-relaxed">
              Current quiz and review evidence suggests spending more time on{" "}
              <strong>{reviewTarget.label}</strong>. This is an estimate from observed answers,
              not a claim about the cause of difficulty.
            </p>
          </div>
          <LinkButton href={`/course/${courseId}/skills/${reviewTarget.id}`} variant="primary">
            Practice this concept
          </LinkButton>
          <LinkButton href={`/course/${courseId}/skills/${reviewTarget.id}#taught`} variant="secondary">
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
        title="By-chapter view isn't built yet"
        className="rounded-[6px] px-3 py-1.5 text-muted-foreground disabled:cursor-not-allowed disabled:opacity-45"
      >
        By chapter
      </button>
    </div>
  );
}
