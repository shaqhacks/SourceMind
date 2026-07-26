"use client";

import Link from "next/link";

import ErrorBanner from "@/components/ErrorBanner";
import Badge from "@/components/ui/Badge";
import Card from "@/components/ui/Card";
import EmptyState from "@/components/ui/EmptyState";
import ProgressBar from "@/components/ui/ProgressBar";
import Skeleton from "@/components/ui/Skeleton";
import StatTile from "@/components/ui/StatTile";
import { MISSED_QUESTIONS, SAMPLE_DATA_LABEL, blockedBy, getSkill } from "@/lib/skills/placeholder";

import { STATUS_BADGE_TONE, STATUS_BAR_TONE, STATUS_LABEL, joinNames } from "./format";
import LinkButton from "./LinkButton";
import { useCourseTitle } from "./useCourseTitle";

export interface CompetencyDetailViewProps {
  courseId: string;
  skillId: string;
}

/**
 * Competency detail page (design handoff §8). Skill/missed-question data is
 * synchronous sample data from lib/skills/placeholder.ts; only the course
 * title comes from the real API. See SkillMapView's header comment for why.
 */
export default function CompetencyDetailView({ courseId, skillId }: CompetencyDetailViewProps) {
  const { title: courseTitle, error, reload } = useCourseTitle(courseId);
  const skill = getSkill(skillId);

  if (error) {
    return (
      <div className="mx-auto w-full max-w-[880px] px-9 py-8">
        <ErrorBanner status={error.status} message={error.message} onRetry={reload} />
      </div>
    );
  }

  if (courseTitle === null) {
    return (
      <div className="mx-auto flex w-full max-w-[880px] flex-col gap-4 px-9 py-8">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-9 w-80" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (skill === undefined) {
    return (
      <div className="mx-auto w-full max-w-[880px] px-9 py-8">
        <EmptyState
          icon="🧭"
          title="Skill not found"
          body="This skill isn't in the sample skill map for this course."
          cta={
            <LinkButton href={`/course/${courseId}/skills`} variant="primary">
              Back to the skill map
            </LinkButton>
          }
        />
      </div>
    );
  }

  const blocked = blockedBy(skill.id);
  const missed = MISSED_QUESTIONS[skill.id] ?? [];
  const primaryTaught = skill.taughtIn[0];

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
          <span className="text-muted-foreground">{skill.name}</span>
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-[34px]">{skill.name}</h1>
          <Badge tone={STATUS_BADGE_TONE[skill.status]}>
            {STATUS_LABEL[skill.status]} · {skill.mastery} mastery
          </Badge>
          <Badge tone="neutral">{SAMPLE_DATA_LABEL}</Badge>
        </div>
        {blocked.length > 0 && (
          <p className="mt-1.5 text-sm text-muted-foreground">
            Blocks{" "}
            <strong className="text-foreground">{joinNames(blocked.map((n) => n.name))}</strong>
          </p>
        )}
      </div>

      <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-3">
        <StatTile
          value={skill.mastery}
          label="Mastery"
          hint={
            <ProgressBar
              percent={skill.mastery}
              label={`${skill.name} mastery`}
              tone={STATUS_BAR_TONE[skill.status]}
            />
          }
        />
        {/* No cards/quiz data model exists yet for skills (placeholder.ts
            has none) — these two tiles show the same illustrative numbers
            everywhere, clearly marked, rather than a fabricated per-skill
            figure. */}
        <StatTile
          value="5"
          label="Cards on this skill"
          hint={<span className="text-xs text-muted-foreground">3 due now · graded Hard ×3 (sample)</span>}
        />
        <StatTile
          value="2/5"
          label="Quiz record"
          hint={<span className="text-xs text-muted-foreground">last two attempts (sample)</span>}
        />
      </div>

      <section id="taught" className="flex flex-col gap-3">
        <h4 className="text-base font-semibold">Where this skill is taught — review these</h4>
        {skill.taughtIn.map((t, i) => (
          <Card key={`${t.chapterLabel}-${t.sectionTitle}`} className="flex flex-row items-center gap-4 py-4">
            <div className="min-w-0 flex-1">
              <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                {t.chapterLabel}
              </span>
              <p className="mt-1 text-[15px] font-bold">{t.sectionTitle}</p>
              <p className="mt-0.5 text-sm text-muted-foreground">{t.relevance}</p>
            </div>
            {i === 0 && <Badge tone="accent">Most relevant</Badge>}
            <LinkButton href={`/course/${courseId}`} variant={i === 0 ? "primary" : "secondary"} className="text-xs">
              Re-read
            </LinkButton>
          </Card>
        ))}
      </section>

      <section className="flex flex-col gap-3">
        <h4 className="text-base font-semibold">Questions you missed on this skill</h4>
        {missed.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No missed questions recorded for this skill yet.
          </p>
        ) : (
          missed.map((m) => (
            <Card key={m.question} className="flex flex-col gap-2 py-4">
              <p className="text-sm font-semibold">&quot;{m.question}&quot;</p>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="accent">You answered: {m.yourAnswer}</Badge>
                <Badge tone="good">Correct: {m.correctAnswer}</Badge>
              </div>
              <p className="text-xs text-muted-foreground">{m.source}</p>
            </Card>
          ))
        )}
      </section>

      <Card className="flex flex-row items-center gap-4 py-5 shadow-md">
        <div className="flex-1">
          <span className="text-xs font-semibold uppercase tracking-wide text-accent-800">Fix plan</span>
          <p className="mt-1.5 text-[15px] leading-relaxed">
            {primaryTaught
              ? `Re-read "${primaryTaught.sectionTitle}", then drill this skill's cards.`
              : "Drill this skill's cards."}
            {blocked.length > 0 && ` That should unblock ${joinNames(blocked.map((n) => n.name))}.`}
          </p>
        </div>
        <LinkButton href={`/course/${courseId}`} variant="primary">
          {primaryTaught ? `Start with ${primaryTaught.sectionTitle}` : "Open the reader"}
        </LinkButton>
        <LinkButton href="/review" variant="secondary">
          Drill cards
        </LinkButton>
      </Card>
    </div>
  );
}
