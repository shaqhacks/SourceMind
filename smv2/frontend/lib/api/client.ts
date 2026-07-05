import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

const baseUrl =
  process.env.NEXT_PUBLIC_SMV2_API_URL ?? "http://localhost:8000";

export const client = createClient<paths>({ baseUrl });

export type JobOut = components["schemas"]["JobOut"];
export type JobCreate = components["schemas"]["JobCreate"];

/**
 * Normalized result shape for every API helper below. `status` is undefined
 * when the request never reached the server (network failure) — ErrorBanner
 * treats a missing status the same as a 5xx: retryable.
 */
export interface ApiResult<T> {
  data?: T;
  error?: unknown;
  status?: number;
}

async function request<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<ApiResult<T>> {
  try {
    const { data, error, response } = await promise;
    return { data, error, status: response.status };
  } catch (err) {
    return { error: err };
  }
}

export function getHealth() {
  return request(client.GET("/health"));
}

export function listJobs() {
  return request(client.GET("/api/jobs"));
}

export function createJob(body: JobCreate) {
  return request(client.POST("/api/jobs", { body }));
}

export function getJob(jobId: string) {
  return request(
    client.GET("/api/jobs/{job_id}", { params: { path: { job_id: jobId } } }),
  );
}
