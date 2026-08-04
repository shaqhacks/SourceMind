"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import Badge from "@/components/ui/Badge";
import Card from "@/components/ui/Card";
import EmptyState from "@/components/ui/EmptyState";
import ProgressBar from "@/components/ui/ProgressBar";
import Skeleton from "@/components/ui/Skeleton";
import StatTile from "@/components/ui/StatTile";
import { getSkillDetail, type SkillDetailOut } from "@/lib/api/client";
import { describeError, type FetchError } from "@/lib/api/errors";

import { STATUS_BADGE_TONE, STATUS_BAR_TONE, STATUS_LABEL, type SkillStatus } from "./format";
import LinkButton from "./LinkButton";
import { useCourseTitle } from "./useCourseTitle";

export interface CompetencyDetailViewProps {
  courseId: string;
  skillId: string;
}

/** "Jul 24" — attempted_at has no chapter/attempt-number context left once
 * flattened to a single missed question, so this is the honest amount of
 * context a date-only stamp can carry (no fabricated "attempt N" count). */
function formatAttemptDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/**
 * Competency detail page (design handoff §8) — reads the real competency
 * graph via GET /api/courses/{course_id}/skills/{concept_id}. Only the
 * course title is a separate fetch (useCourseTitle); everything else comes
 * straight off the one SkillDetailOut response.
 */
export default function CompetencyDetailView({ courseId, skillId }: CompetencyDetailViewProps) {
  const { title: courseTitle, error: titleError, reload: reloadTitle } = useCourseTitle(courseId);

  const [detail, setDetail] = useState<SkillDetailOut | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [detailError, setDetailError] = useState<FetchError | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const reloadDetail = useCallback(() => setReloadToken((n) => n + 1), []);

  useEffect(() => {
    let active = true;
    getSkillDetail(courseId, skillId).then(({ data, status }) => {
      if (!active) return;
      if (data) {
        setDetail(data);
        setNotFound(false);
        setDetailError(null);
      } else if (status === 404) {
        setDetail(null);
        setNotFound(true);
        setDetailError(null);
      } else {
        setDetailError(describeError(status, "Loading skill"));
      }
    });
    return () => {
      active = false;
    };
  }, [courseId, skillId, reloadToken]);

  const error = titleError ?? detailError;
  if (error) {
    return (
      <div className="mx-auto w-full max-w-[880px] px-9 py-8">
        <ErrorBanner
          status={error.status}
          message={error.message}
          onRetry={titleError ? reloadTitle : reloadDetail}
        />
      </div>
    );
  }

  if (courseTitle === null || (detail === null && !notFound)) {
    return (
      <div className="mx-auto flex w-full max-w-[880px] flex-col gap-4 px-9 py-8">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-9 w-80" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (notFound || detail === null) {
    return (
      <div className="mx-auto w-full max-w-[880px] px-9 py-8">
        <EmptyState
          icon="🧭"
          title="Skill not found"
          body="This skill isn't in this course's skill map."
          cta={
            <LinkButton href={`/course/${courseId}/skills`} variant="primary">
              Back to the skill map
            </LinkButton>
          }
        />
      </div>
    );
  }

  const { node, taught_in: taughtIn, missed_questions: missed } = detail;
  const status = node.status as SkillStatus;
  const primaryTaught = taughtIn[0];
  const quizTotal = detail.quiz_correct + detail.quiz_wrong;
  const readinessPercent = node.readiness_estimate == null ? null : Math.round(node.readiness_estimate * 100);
  const uncertaintyPercent = node.uncertainty == null ? null : Math.round(node.uncertainty * 100);

  return (
    <div className="mx-auto flex w-full max-w-[880px] flex-col gap-6 px-9 py-8">
      <div>
        <p className="mb-1 text-sm font-semibold">
          <Link href={`/course/${courseId}`} className="text-accent-700 hover:underline">
            {courseTitle}
          </Link>
          <span className="text-muted-foreground opacity-60"> / </span>
          <Link href={`/course/${courseId}/skills`} className="text-accent-700 hover:underline">
            Skill map
          </Link>
          <span className="text-muted-foreground opacity-60"> / </span>
          <span className="text-muted-foreground">{node.label}</span>
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-[34px]">{node.label}</h1>
          <Badge tone={STATUS_BADGE_TONE[status]}>
            {STATUS_LABEL[status]}
            {readinessPercent == null ? " · estimate pending" : ` · ${readinessPercent}% readiness`}
          </Badge>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-3">
        <StatTile
          value={readinessPercent == null ? "—" : `${readinessPercent}%`}
          label="Readiness estimate"
          hint={readinessPercent == null ? (
            <span className="text-xs text-muted-foreground">More varied evidence is needed.</span>
          ) : (
            <ProgressBar percent={readinessPercent} label={`${node.label} readiness`} tone={STATUS_BAR_TONE[status]} />
          )}
        />
        <StatTile
          value={node.distinct_item_count ?? 0}
          label="Distinct evidence items"
          hint={uncertaintyPercent == null ? undefined : `Uncertainty range: ${uncertaintyPercent} points`}
        />
        <StatTile
          value={quizTotal === 0 ? "—" : `${detail.quiz_correct}/${quizTotal}`}
          label="Quiz record"
        />
      </div>

      <Card className="flex flex-col gap-3 py-5">
        <div>
          <h4 className="text-base font-semibold">Why this estimate</h4>
          <p className="mt-1 text-sm text-muted-foreground">
            Based on {node.distinct_item_count ?? 0} distinct item{(node.distinct_item_count ?? 0) === 1 ? "" : "s"}
            {node.last_evidence_at ? ` through ${formatAttemptDate(node.last_evidence_at)}` : ""}.
            Repeated exposure to the same item is discounted.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <StatTile
            value={node.quiz_estimate == null ? "—" : `${Math.round(node.quiz_estimate * 100)}%`}
            label="Quiz / application evidence"
          />
          <StatTile
            value={node.review_estimate == null ? "—" : `${Math.round(node.review_estimate * 100)}%`}
            label="Flashcard / retrieval evidence"
          />
        </div>
      </Card>

      <section id="taught" className="flex flex-col gap-3">
        <h4 className="text-base font-semibold">Where this skill is taught — review these</h4>
        {taughtIn.length === 0 ? (
          <p className="text-sm text-muted-foreground">Not linked to any section yet.</p>
        ) : (
          taughtIn.map((t, i) => (
            <Card key={t.section_id} className="flex flex-row items-center gap-4 py-4">
              <div className="min-w-0 flex-1">
                {t.chapter_label && (
                  <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    {t.chapter_label}
                  </span>
                )}
                <p className="mt-1 text-[15px] font-bold">{t.title}</p>
                {t.relevance_md && <p className="mt-0.5 text-sm text-muted-foreground">{t.relevance_md}</p>}
              </div>
              {i === 0 && <Badge tone="accent">Most relevant</Badge>}
              <LinkButton
                href={`/course/${courseId}?section=${t.section_id}`}
                variant={i === 0 ? "primary" : "secondary"}
                className="text-xs"
              >
                Re-read
              </LinkButton>
            </Card>
          ))
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h4 className="text-base font-semibold">Questions you missed on this skill</h4>
        {missed.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No missed questions recorded for this skill yet.
          </p>
        ) : (
          missed.map((m, i) => (
            <Card key={`${m.source_test_id}-${i}`} className="flex flex-col gap-2 py-4">
              <p className="text-sm font-semibold">&quot;{m.question}&quot;</p>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="accent">You answered: {m.your_answer ?? "Skipped"}</Badge>
                <Badge tone="good">Correct: {m.correct_answer}</Badge>
              </div>
              <p className="text-xs text-muted-foreground">
                Test attempt · {formatAttemptDate(m.attempted_at)}
              </p>
            </Card>
          ))
        )}
      </section>

      <Card className="flex flex-row items-center gap-4 py-5 shadow-md">
        <div className="flex-1">
          <span className="text-xs font-semibold uppercase tracking-wide text-accent-800">Next study step</span>
          <p className="mt-1.5 text-[15px] leading-relaxed">
            {primaryTaught
              ? `Re-read "${primaryTaught.title}", then answer varied questions and review cards linked to this concept.`
              : "Answer varied questions and review cards linked to this concept."}
          </p>
        </div>
        <LinkButton
          href={primaryTaught ? `/course/${courseId}?section=${primaryTaught.section_id}` : `/course/${courseId}`}
          variant="primary"
        >
          {primaryTaught ? `Start with ${primaryTaught.title}` : "Open the reader"}
        </LinkButton>
        <LinkButton href={`/review?course=${courseId}`} variant="secondary">
          Practice and review
        </LinkButton>
      </Card>
    </div>
  );
}
