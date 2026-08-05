"use client";

import Link from "next/link";

import { recoveryHref } from "@/components/RecoveryBanner";
import Button from "@/components/ui/Button";
import type { JobOut, LlmStatusOut } from "@/lib/api/client";

export interface JobGroupProps {
  courseId: string;
  type: string;
  jobs: JobOut[];
  highlightedJobId: string | null;
  readiness: LlmStatusOut | null;
  onRetry: (jobId: string) => void;
}

function labelType(type: string): string {
  return type.replaceAll("_", " ");
}

function sectionId(job: JobOut): string | null {
  return job.payload && typeof job.payload.section_id === "string" ? job.payload.section_id : null;
}

export default function JobGroup({ courseId, type, jobs, highlightedJobId, readiness, onRetry }: JobGroupProps) {
  const readinessAllowsRetry = readiness?.available !== false && readiness?.capabilities.completion !== false;
  return (
    <section className="flex flex-col gap-3">
      <h3 className="font-heading text-lg capitalize">{labelType(type)}</h3>
      {jobs.map((job) => {
        const section = sectionId(job);
        const highlighted = job.id === highlightedJobId;
        return (
          <article
            key={job.id}
            data-testid={`job-${job.id}`}
            aria-current={highlighted ? "true" : undefined}
            className={`rounded-md border border-divider bg-surface-raised p-4 ${highlighted ? "ring-2 ring-accent" : ""}`}
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="font-mono text-xs text-muted-foreground">{job.id}</p>
                <p className="mt-1 text-sm font-semibold capitalize">{job.status}</p>
                {job.error && <p className="mt-1 text-sm text-status-serious">{job.error}</p>}
              </div>
              {job.status === "failed" && job.retryable && readinessAllowsRetry ? (
                <Button size="sm" onClick={() => onRetry(job.id)}>
                  Retry
                </Button>
              ) : null}
            </div>
            <div className="mt-3 flex flex-wrap gap-3 text-sm">
              <Link href={`/course/${courseId}`} className="text-accent hover:underline">
                Open course {courseId}
              </Link>
              {section && (
                <Link href={`/course/${courseId}?section=${encodeURIComponent(section)}`} className="text-accent hover:underline">
                  Open section {section}
                </Link>
              )}
              {job.status === "failed" && !readinessAllowsRetry && (
                <Link href={recoveryHref({ errorDetail: readiness })} className="text-accent hover:underline">
                  Open Settings
                </Link>
              )}
            </div>
          </article>
        );
      })}
    </section>
  );
}
