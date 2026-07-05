import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

/**
 * Base URL for the API. Exported (not just used internally) because
 * lib/hooks/useJobEvents.ts needs it too: EventSource has no openapi-fetch
 * equivalent, so that hook builds its own URL against this constant instead
 * of going through `client` below. It is the one sanctioned exception to
 * "every request goes through this file's fetch boundary".
 */
export const API_BASE = process.env.NEXT_PUBLIC_SMV2_API_URL ?? "http://localhost:8000";

export const client = createClient<paths>({ baseUrl: API_BASE });

export type JobOut = components["schemas"]["JobOut"];
export type JobCreate = components["schemas"]["JobCreate"];
export type CourseOut = components["schemas"]["CourseOut"];
export type CourseCreate = components["schemas"]["CourseCreate"];

/**
 * Normalized result shape for every API helper below. `status` is undefined
 * when the request never reached the server (network failure) — ErrorBanner
 * treats a missing status the same as a 5xx: retryable. `ok` mirrors
 * fetch's `Response.ok` (2xx) — use it instead of `data` truthiness for
 * endpoints like delete that return no body on success.
 */
export interface ApiResult<T> {
  data?: T;
  error?: unknown;
  status?: number;
  ok: boolean;
}

async function request<T>(
  promise: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<ApiResult<T>> {
  try {
    const { data, error, response } = await promise;
    return { data, error, status: response.status, ok: response.ok };
  } catch (err) {
    return { error: err, ok: false };
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

export function listCourses() {
  return request(client.GET("/api/courses"));
}

export function createCourse(body: CourseCreate) {
  return request(client.POST("/api/courses", { body }));
}

export function getCourse(courseId: string) {
  return request(
    client.GET("/api/courses/{course_id}", { params: { path: { course_id: courseId } } }),
  );
}

export function deleteCourse(courseId: string) {
  return request(
    client.DELETE("/api/courses/{course_id}", { params: { path: { course_id: courseId } } }),
  );
}
