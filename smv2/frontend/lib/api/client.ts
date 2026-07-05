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
export type SectionOut = components["schemas"]["SectionOut"];
export type SectionDetailOut = components["schemas"]["SectionDetailOut"];
export type ProgressOut = components["schemas"]["ProgressOut"];
export type ProgressIn = components["schemas"]["ProgressIn"];
export type AssetOut = components["schemas"]["AssetOut"];
export type IngestStartOut = components["schemas"]["IngestStartOut"];
export type GenerateLessonOut = components["schemas"]["GenerateLessonOut"];
export type LessonEstimateOut = components["schemas"]["LessonEstimateOut"];
export type GenerateAllLessonsOut = components["schemas"]["GenerateAllLessonsOut"];
export type LlmUsageOut = components["schemas"]["LlmUsageOut"];
export type OutlineOp =
  | components["schemas"]["RenameOp"]
  | components["schemas"]["ReorderOp"]
  | components["schemas"]["DeleteOp"]
  | components["schemas"]["MergeOp"]
  | components["schemas"]["SplitOp"];

/**
 * JobOut.status values that mean the job will never emit another SSE event.
 * Exported so useJobEvents.ts (the stream consumer) and findActiveIngestJob
 * below (a plain REST scan) agree on the same set instead of each keeping
 * its own copy of this literal.
 */
export const TERMINAL_JOB_STATUSES = new Set(["succeeded", "failed"]);

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

export function listAssets(courseId: string) {
  return request(
    client.GET("/api/courses/{course_id}/assets", {
      params: { path: { course_id: courseId } },
    }),
  );
}

export function uploadAsset(courseId: string, file: File) {
  const body = new FormData();
  body.append("file", file);
  return request(
    client.POST("/api/courses/{course_id}/assets", {
      params: { path: { course_id: courseId } },
      // Body_upload_asset types `file` as a plain `string` — openapi-typescript
      // has no separate binary/File type — but this is a multipart request:
      // openapi-fetch's defaultBodySerializer passes a FormData instance
      // through untouched (and lets the browser set the multipart boundary),
      // so a real FormData is the correct runtime value despite the TS shape.
      body: body as unknown as { file: string },
    }),
  );
}

export function startIngest(courseId: string) {
  return request(
    client.POST("/api/courses/{course_id}/ingest", {
      params: { path: { course_id: courseId } },
    }),
  );
}

export function editOutline(courseId: string, operations: OutlineOp[]) {
  return request(
    client.PATCH("/api/courses/{course_id}/outline", {
      params: { path: { course_id: courseId } },
      body: { operations },
    }),
  );
}

export function listSections(courseId: string) {
  return request(
    client.GET("/api/courses/{course_id}/sections", {
      params: { path: { course_id: courseId } },
    }),
  );
}

export function getSection(sectionId: string) {
  return request(
    client.GET("/api/sections/{section_id}", { params: { path: { section_id: sectionId } } }),
  );
}

export function getProgress(courseId: string) {
  return request(
    client.GET("/api/courses/{course_id}/progress", {
      params: { path: { course_id: courseId } },
    }),
  );
}

export function saveProgress(courseId: string, body: ProgressIn) {
  return request(
    client.PUT("/api/courses/{course_id}/progress", {
      params: { path: { course_id: courseId } },
      body,
    }),
  );
}

/**
 * Not a fetch — export is a plain GET returning a zip binary with a
 * Content-Disposition: attachment header, so a plain `<a href download>`
 * lets the browser handle the download directly with no JS-side blob
 * juggling and no CORS concerns (downloads via `download` aren't fetch/XHR).
 */
export function exportCourseUrl(courseId: string): string {
  return `${API_BASE}/api/courses/${encodeURIComponent(courseId)}/export`;
}

function payloadCourseId(payload: { [key: string]: unknown } | null | undefined): string | null {
  return payload && typeof payload.course_id === "string" ? payload.course_id : null;
}

function latestByCreatedAt(jobs: JobOut[]): JobOut | null {
  if (jobs.length === 0) return null;
  return jobs.reduce((latest, job) =>
    new Date(job.created_at).getTime() > new Date(latest.created_at).getTime() ? job : latest,
  );
}

/**
 * There is no course->job index in the API (CourseOut has no job_id, JobOut
 * has no course_id column — course_id only lives inside the untyped
 * `payload` dict the ingest job was created with). So rediscovering "the
 * ingest job for this course" after a page reload means scanning the (last
 * 50, unfiltered, unpaginated) job list client-side. Fine at this app's
 * scale; revisit if job volume grows.
 */
export async function findActiveIngestJob(courseId: string): Promise<JobOut | null> {
  const { data } = await listJobs();
  if (!data) return null;
  return latestByCreatedAt(
    data.filter(
      (job) =>
        job.type === "ingest" &&
        !TERMINAL_JOB_STATUSES.has(job.status) &&
        payloadCourseId(job.payload) === courseId,
    ),
  );
}

/**
 * Same scan, but regardless of status — for a course already sitting in
 * "ingest_failed" (from a prior session), this is how a course card finds
 * its failed job's `.error` text: there's no per-asset-error listing
 * endpoint, so the job's own error message is the closest available detail.
 */
export async function findLatestIngestJob(courseId: string): Promise<JobOut | null> {
  const { data } = await listJobs();
  if (!data) return null;
  return latestByCreatedAt(
    data.filter((job) => job.type === "ingest" && payloadCourseId(job.payload) === courseId),
  );
}

export function generateLesson(sectionId: string, force = false) {
  return request(
    client.POST("/api/sections/{section_id}/lesson", {
      params: { path: { section_id: sectionId }, query: { force } },
    }),
  );
}

export function generateAllLessons(courseId: string) {
  return request(
    client.POST("/api/courses/{course_id}/lessons", {
      params: { path: { course_id: courseId } },
    }),
  );
}

export function getLessonEstimate(sectionId: string) {
  return request(
    client.GET("/api/sections/{section_id}/lesson/estimate", {
      params: { path: { section_id: sectionId } },
    }),
  );
}

export function getLlmUsage(courseId?: string) {
  return request(
    client.GET("/api/llm/usage", {
      params: { query: { course_id: courseId } },
    }),
  );
}

function payloadSectionId(payload: { [key: string]: unknown } | null | undefined): string | null {
  return payload && typeof payload.section_id === "string" ? payload.section_id : null;
}

/**
 * Same rediscovery problem as findActiveIngestJob, for lesson generation:
 * a section's lesson_status can be "queued"/"generating" from a job
 * started in a prior session (or by generate_all_lessons), with no job_id
 * carried on the section itself.
 */
export async function findActiveLessonJob(sectionId: string): Promise<JobOut | null> {
  const { data } = await listJobs();
  if (!data) return null;
  return latestByCreatedAt(
    data.filter(
      (job) =>
        job.type === "generate_lesson" &&
        !TERMINAL_JOB_STATUSES.has(job.status) &&
        payloadSectionId(job.payload) === sectionId,
    ),
  );
}
