export interface ErrorBannerProps {
  /** HTTP status of the failed request, if one was received (undefined = network failure). */
  status?: number;
  message: string;
  onRetry?: () => void;
}

/**
 * A request is retryable when it never reached the server (no status) or
 * the server itself failed (5xx). 4xx means the request was rejected on its
 * merits — retrying with the same input won't help.
 */
function isRetryable(status?: number): boolean {
  return status === undefined || status >= 500;
}

export default function ErrorBanner({ status, message, onRetry }: ErrorBannerProps) {
  const retryable = isRetryable(status);

  return (
    <div
      role="alert"
      className="flex items-center justify-between gap-4 rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-100"
    >
      <span>{message}</span>
      {retryable && onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 rounded border border-red-400 px-3 py-1 font-medium hover:bg-red-100 dark:border-red-700 dark:hover:bg-red-900"
        >
          Retry
        </button>
      ) : null}
    </div>
  );
}
