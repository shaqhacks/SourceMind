import { UNSUPPORTED_SOURCE_FORMAT_MESSAGE } from "@/lib/importFormats";
import type { ApiErrorDetail } from "@/lib/api/client";

export interface FetchError {
  status?: number;
  message: string;
  detail?: ApiErrorDetail | null;
}

function optionalString(value: unknown): string | null | undefined {
  return value === null || typeof value === "string" ? value : undefined;
}

export function apiErrorDetail(error: unknown): ApiErrorDetail | null {
  if (!error || typeof error !== "object" || !("detail" in error)) return null;
  const detail = (error as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object") return null;
  const candidate = detail as Record<string, unknown>;
  const code = optionalString(candidate.code);
  const failureCategory = optionalString(candidate.failure_category);
  const message = optionalString(candidate.message);
  const remediation = optionalString(candidate.remediation);
  if (
    code === undefined ||
    failureCategory === undefined ||
    message === undefined ||
    remediation === undefined
  ) {
    return null;
  }
  return { code, failure_category: failureCategory, message, remediation };
}

/** A request is retryable when it never reached the server (no status) or
 * the server itself failed (5xx) — see ErrorBanner's own isRetryable. This
 * just builds the display message; callers decide retryability. */
export function describeError(
  status: number | undefined,
  action: string,
  error?: unknown,
): FetchError {
  const detail = apiErrorDetail(error);
  if (detail?.code === "unsupported_source_format") {
    return {
      status,
      message: UNSUPPORTED_SOURCE_FORMAT_MESSAGE,
      detail,
    };
  }
  if (detail?.message) return { status, message: detail.message, detail };
  if (status === undefined) {
    return { message: `${action}: could not reach the API. Is the backend running?`, detail };
  }
  return { status, message: `${action} failed (HTTP ${status}).`, detail };
}
