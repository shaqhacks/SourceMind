import { UNSUPPORTED_SOURCE_FORMAT_MESSAGE } from "@/lib/importFormats";

export interface FetchError {
  status?: number;
  message: string;
}

function errorCode(error: unknown): string | null {
  if (!error || typeof error !== "object") return null;
  const detail = "detail" in error ? (error as { detail?: unknown }).detail : null;
  if (!detail || typeof detail !== "object") return null;
  const code = "code" in detail ? (detail as { code?: unknown }).code : null;
  return typeof code === "string" ? code : null;
}

/** A request is retryable when it never reached the server (no status) or
 * the server itself failed (5xx) — see ErrorBanner's own isRetryable. This
 * just builds the display message; callers decide retryability. */
export function describeError(
  status: number | undefined,
  action: string,
  error?: unknown,
): FetchError {
  if (errorCode(error) === "unsupported_source_format") {
    return {
      status,
      message: UNSUPPORTED_SOURCE_FORMAT_MESSAGE,
    };
  }
  if (status === undefined) {
    return { message: `${action}: could not reach the API. Is the backend running?` };
  }
  return { status, message: `${action} failed (HTTP ${status}).` };
}
