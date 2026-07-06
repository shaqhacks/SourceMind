export interface FetchError {
  status?: number;
  message: string;
}

/** A request is retryable when it never reached the server (no status) or
 * the server itself failed (5xx) — see ErrorBanner's own isRetryable. This
 * just builds the display message; callers decide retryability. */
export function describeError(status: number | undefined, action: string): FetchError {
  if (status === undefined) {
    return { message: `${action}: could not reach the API. Is the backend running?` };
  }
  return { status, message: `${action} failed (HTTP ${status}).` };
}
