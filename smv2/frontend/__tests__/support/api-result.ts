import type { ApiResult } from "@/lib/api/client";

/** A successful ApiResult<T> mock — status defaults to 200. */
export function ok<T>(data: T, status = 200): ApiResult<T> {
  return { status, ok: true, data };
}

/** A failed ApiResult<T> mock — omit `status` for a network failure (no
 * response reached the client), matching the real client's convention. */
export function err<T>(status?: number): ApiResult<T> {
  return { status, ok: false };
}
