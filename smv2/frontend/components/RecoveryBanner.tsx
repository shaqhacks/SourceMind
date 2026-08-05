"use client";

import Link from "next/link";

import ErrorBanner from "@/components/ErrorBanner";

export interface RecoveryBannerProps {
  message: string;
  onRetry?: () => void;
  jobId?: string | null;
  failureCategory?: string | null;
}

export function recoveryHref({
  jobId,
  failureCategory,
  message,
}: {
  jobId?: string | null;
  failureCategory?: string | null;
  message?: string | null;
}): string {
  const normalized = `${failureCategory ?? ""} ${message ?? ""}`.toLowerCase();
  if (
    normalized.includes("missing_credentials") ||
    normalized.includes("provider-not-configured") ||
    normalized.includes("not configured") ||
    normalized.includes("api_key")
  ) {
    return "/settings";
  }
  return jobId ? `/jobs?job=${encodeURIComponent(jobId)}` : "/jobs";
}

export default function RecoveryBanner({
  message,
  onRetry,
  jobId,
  failureCategory,
}: RecoveryBannerProps) {
  const href = recoveryHref({ jobId, failureCategory, message });
  const linkLabel = href === "/settings" ? "Open Settings" : "View job details";

  return (
    <div className="flex flex-col gap-2">
      <ErrorBanner message={message} onRetry={onRetry} />
      <Link href={href} className="self-start text-sm font-medium text-accent hover:underline">
        {linkLabel}
      </Link>
    </div>
  );
}
