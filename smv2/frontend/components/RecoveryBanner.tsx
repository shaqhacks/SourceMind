"use client";

import Link from "next/link";

import ErrorBanner from "@/components/ErrorBanner";
import type { ApiErrorDetail } from "@/lib/api/client";

export interface RecoveryBannerProps {
  message: string;
  onRetry?: () => void;
  jobId?: string | null;
  errorDetail?: ApiErrorDetail | null;
}

export function recoveryHref({
  jobId,
  errorDetail,
}: {
  jobId?: string | null;
  errorDetail?: ApiErrorDetail | null;
}): string {
  if (isReadinessFailure(errorDetail)) {
    return "/settings";
  }
  return jobId ? `/jobs?job=${encodeURIComponent(jobId)}` : "/jobs";
}

export function recoveryAllowsRetry(errorDetail?: ApiErrorDetail | null): boolean {
  return !isReadinessFailure(errorDetail);
}

function isReadinessFailure(errorDetail?: ApiErrorDetail | null): boolean {
  return (
    errorDetail?.code === "llm_readiness_unavailable" ||
    errorDetail?.failure_category === "missing_credentials" ||
    errorDetail?.failure_category === "unknown_provider" ||
    errorDetail?.failure_category === "unreachable" ||
    errorDetail?.failure_category === "ollama_model_unavailable" ||
    errorDetail?.failure_category === "ollama_embed_model_unavailable"
  );
}

export default function RecoveryBanner({
  message,
  onRetry,
  jobId,
  errorDetail,
}: RecoveryBannerProps) {
  const href = recoveryHref({ jobId, errorDetail });
  const linkLabel = href === "/settings" ? "Open Settings" : "View job details";
  const retry = onRetry && recoveryAllowsRetry(errorDetail) ? onRetry : undefined;

  return (
    <div className="flex flex-col gap-2">
      <ErrorBanner message={message} onRetry={retry} />
      <Link href={href} className="self-start text-sm font-medium text-accent hover:underline">
        {linkLabel}
      </Link>
    </div>
  );
}
