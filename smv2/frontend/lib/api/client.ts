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
export type CardOut = components["schemas"]["CardOut"];
export type UpdateCardIn = components["schemas"]["UpdateCardIn"];
export type GenerateCardsOut = components["schemas"]["GenerateCardsOut"];
export type ReviewQueueOut = components["schemas"]["ReviewQueueOut"];
export type ReviewQueueCardOut = components["schemas"]["ReviewQueueCardOut"];
export type GradeCardIn = components["schemas"]["GradeCardIn"];
export type GradeCardOut = components["schemas"]["GradeCardOut"];
export type ReviewSummaryOut = components["schemas"]["ReviewSummaryOut"];
export type CourseReviewSummaryOut = components["schemas"]["CourseReviewSummaryOut"];
export type GenerateTestOut = components["schemas"]["GenerateTestOut"];
export type GenerateTestIn = components["schemas"]["GenerateTestIn"];
export type ChapterOut = components["schemas"]["ChapterOut"];
export type ChapterTestStatsOut = components["schemas"]["ChapterTestStatsOut"];
export type StudyNextItemOut = components["schemas"]["StudyNextItemOut"];
export type TestAttemptOut = components["schemas"]["TestAttemptOut"];
export type TestQuestionOut = components["schemas"]["TestQuestionOut"];
export type TestAttemptSummaryOut = components["schemas"]["TestAttemptSummaryOut"];
export type TestSummaryOut = components["schemas"]["TestSummaryOut"];
export type RetakeTestOut = components["schemas"]["RetakeTestOut"];
export type SubmitTestOut = components["schemas"]["SubmitTestOut"];
export type SubmitTestQuestionResultOut = components["schemas"]["SubmitTestQuestionResultOut"];
export type PracticeAssessmentOut = components["schemas"]["PracticeAssessmentOut"];
export type PracticeQuestionOut = components["schemas"]["PracticeQuestionOut"];
export type PracticeConceptOut = components["schemas"]["PracticeConceptOut"];
export type PracticeAnsweredOut = components["schemas"]["PracticeAnsweredOut"];
export type SubmitPracticeAnswerIn = components["schemas"]["SubmitPracticeAnswerIn"];
export type SubmitPracticeAnswerOut = components["schemas"]["SubmitPracticeAnswerOut"];
export type ChatOut = components["schemas"]["ChatOut"];
export type ChatCitationOut = components["schemas"]["ChatCitationOut"];
export type ChatTurnOut = components["schemas"]["ChatTurnOut"];
export type ChatSelectionIn = components["schemas"]["ChatSelectionIn"];
export type HighlightOut = components["schemas"]["HighlightOut"];
export type HighlightIn = components["schemas"]["HighlightIn"];
export type HighlightUpdateIn = components["schemas"]["HighlightUpdateIn"];
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

export function getPracticeAssessment(courseId: string, sectionId: string) {
  return request(
    client.GET("/api/courses/{course_id}/sections/{section_id}/practice-assessment", {
      params: { path: { course_id: courseId, section_id: sectionId } },
    }),
  );
}

export function startPracticeAssessment(courseId: string, sectionId: string) {
  return request(
    client.POST("/api/courses/{course_id}/sections/{section_id}/practice-assessment", {
      params: { path: { course_id: courseId, section_id: sectionId } },
    }),
  );
}

export function submitPracticeAnswer(courseId: string, questionId: string, selectedIndex: number) {
  return request(
    client.POST("/api/courses/{course_id}/practice-questions/{question_id}/answer", {
      params: { path: { course_id: courseId, question_id: questionId } },
      body: { selected_index: selectedIndex },
    }),
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

/**
 * Same rationale as exportCourseUrl: a plain <img src> resource URL is
 * browser-native resource loading, not a request this app's ApiResult/status
 * handling applies to. Markdown.tsx's gated image renderer calls this with
 * the courseId/filename it parsed out of a body_md image reference — never
 * with unvalidated input, since the caller only invokes this after matching
 * the extracted-image src pattern.
 */
export function buildCourseImageUrl(courseId: string, filename: string): string {
  return `${API_BASE}/api/courses/${encodeURIComponent(courseId)}/images/${encodeURIComponent(filename)}`;
}

/**
 * Same rationale as exportCourseUrl/buildCourseImageUrl: pdf.js's own
 * getDocument({ url }) fetches this URL itself (a plain GET returning the
 * raw PDF binary) — it's not a JSON round-trip this app's ApiResult
 * handling applies to, so there's nothing for the generated client to wrap.
 */
export function buildAssetFileUrl(assetId: string): string {
  return `${API_BASE}/api/assets/${encodeURIComponent(assetId)}/file`;
}

/**
 * Same rationale as buildAssetFileUrl: an <iframe src> resource URL is
 * browser-native resource loading, not a request this app's ApiResult
 * handling applies to. Serves one pdf2htmlEX-converted page's
 * self-contained HTML (the "enhanced" pages view).
 */
export function buildAssetHtmlPageUrl(assetId: string, pageNumber: number): string {
  return `${API_BASE}/api/assets/${encodeURIComponent(assetId)}/html/${pageNumber}`;
}

/**
 * Manifest for the enhanced (pdf2htmlEX HTML) pages view — present only
 * once conversion has finished (404 otherwise). get_asset_html_manifest
 * returns a plain JSONResponse with no response_model, so the generated
 * type for its body is `unknown`; the real, stable field names
 * (pages/width_px/height_px) are pinned here and verified directly
 * against app/pipeline/html_conversion.py's own manifest-writing code
 * rather than assumed.
 */
export interface AssetHtmlManifest {
  pages: number;
  width_px: number;
  height_px: number;
}

export async function getAssetHtmlManifest(assetId: string): Promise<ApiResult<AssetHtmlManifest>> {
  const { data, error, status, ok } = await request<unknown>(
    client.GET("/api/assets/{asset_id}/html/manifest", {
      params: { path: { asset_id: assetId } },
    }),
  );
  return { data: data as AssetHtmlManifest | undefined, error, status, ok };
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

export function generateCards(sectionId: string) {
  return request(
    client.POST("/api/sections/{section_id}/cards", {
      params: { path: { section_id: sectionId } },
    }),
  );
}

export function listCards(sectionId: string) {
  return request(
    client.GET("/api/sections/{section_id}/cards", {
      params: { path: { section_id: sectionId } },
    }),
  );
}

/**
 * Inline card editing — the response is a full card under a NEW id
 * (editing front/back changes the content-addressed id), so callers must
 * swap it into their list by the OLD id, not mutate the existing entry
 * in place.
 */
export function patchCard(cardId: string, body: UpdateCardIn) {
  return request(
    client.PATCH("/api/cards/{card_id}", {
      params: { path: { card_id: cardId } },
      body,
    }),
  );
}

/** Deletes a card and its review history (ReviewState/ReviewLog cascade
 * server-side). 204 with no body on success. */
export function deleteCard(cardId: string) {
  return request(
    client.DELETE("/api/cards/{card_id}", { params: { path: { card_id: cardId } } }),
  );
}

/** Same rediscovery need as findActiveLessonJob, for card generation. */
export async function findActiveCardsJob(sectionId: string): Promise<JobOut | null> {
  const { data } = await listJobs();
  if (!data) return null;
  return latestByCreatedAt(
    data.filter(
      (job) =>
        job.type === "generate_cards" &&
        !TERMINAL_JOB_STATUSES.has(job.status) &&
        payloadSectionId(job.payload) === sectionId,
    ),
  );
}

export function getReviewQueue(courseId: string, limit?: number) {
  return request(
    client.GET("/api/courses/{course_id}/review/queue", {
      params: { path: { course_id: courseId }, query: limit === undefined ? {} : { limit } },
    }),
  );
}

export function gradeCard(cardId: string, body: GradeCardIn) {
  return request(
    client.POST("/api/cards/{card_id}/grade", {
      params: { path: { card_id: cardId } },
      body,
    }),
  );
}

export function getReviewSummary() {
  return request(client.GET("/api/review/summary"));
}

/** Ordered "what to study next" suggestions for a course (ADR-022, at most
 * 3, already prioritized by the backend — low test score, then due-card
 * backlog, then never-opened, then stale). */
export function getStudyNext(courseId: string) {
  return request(
    client.GET("/api/courses/{course_id}/study-next", {
      params: { path: { course_id: courseId } },
    }),
  );
}

/**
 * Course-wide by default; pass exactly one of `sectionIds` (an explicit
 * subset) or `chapterLabel` (a single chapter's own practice+content, minus
 * answers sections — the backend excludes those from generation input) to
 * scope it. Passing both is meaningless — the backend's GenerateTestIn
 * doesn't define which one would win, so this is caller error.
 */
export function generateTest(
  courseId: string,
  options?: { sectionIds?: string[]; chapterLabel?: string },
) {
  const body: GenerateTestIn = {};
  if (options?.sectionIds !== undefined) body.section_ids = options.sectionIds;
  if (options?.chapterLabel !== undefined) body.chapter_label = options.chapterLabel;
  return request(
    client.POST("/api/courses/{course_id}/tests", {
      params: { path: { course_id: courseId } },
      body,
    }),
  );
}

export function listTests(courseId: string) {
  return request(
    client.GET("/api/courses/{course_id}/tests", {
      params: { path: { course_id: courseId } },
    }),
  );
}

/** Ordered chapters — sections split into content/practice/answers, plus
 * each chapter's aggregate test_stats (null until it has an attempt). */
export function listChapters(courseId: string) {
  return request(
    client.GET("/api/courses/{course_id}/chapters", {
      params: { path: { course_id: courseId } },
    }),
  );
}

export function getTest(attemptId: string) {
  return request(
    client.GET("/api/tests/{attempt_id}", { params: { path: { attempt_id: attemptId } } }),
  );
}

export function submitTest(attemptId: string, answers: number[]) {
  return request(
    client.POST("/api/tests/{attempt_id}/submit", {
      params: { path: { attempt_id: attemptId } },
      body: { answers },
    }),
  );
}

/** Zero-LLM retake: a fresh TestAttempt on the same questions as `testId`
 * (the persisted Test/deck), no generation job involved. */
export function retakeTest(testId: string) {
  return request(
    client.POST("/api/tests/{test_id}/attempts", {
      params: { path: { test_id: testId } },
    }),
  );
}

/**
 * How many cards are due right now for a course — reuses the
 * already-typed review-queue endpoint (its due/new/total counts are
 * computed independently of `limit`, which only caps the returned
 * `cards` array) rather than needing a new field on submit_test's
 * response; a small limit keeps this call cheap since only the count is
 * used, not the cards themselves.
 */
export async function getDueCountForCourse(courseId: string): Promise<number> {
  const { data } = await getReviewQueue(courseId, 1);
  return data?.due ?? 0;
}

/** Same rediscovery need as findActiveLessonJob, for test generation. */
export async function findActiveTestJob(courseId: string): Promise<JobOut | null> {
  const { data } = await listJobs();
  if (!data) return null;
  return latestByCreatedAt(
    data.filter(
      (job) =>
        job.type === "generate_test" &&
        !TERMINAL_JOB_STATUSES.has(job.status) &&
        payloadCourseId(job.payload) === courseId,
    ),
  );
}

export function listHighlights(courseId: string) {
  return request(
    client.GET("/api/courses/{course_id}/highlights", {
      params: { path: { course_id: courseId } },
    }),
  );
}

export function createHighlight(courseId: string, body: HighlightIn) {
  return request(
    client.POST("/api/courses/{course_id}/highlights", {
      params: { path: { course_id: courseId } },
      body,
    }),
  );
}

export function updateHighlight(highlightId: string, body: HighlightUpdateIn) {
  return request(
    client.PATCH("/api/highlights/{highlight_id}", {
      params: { path: { highlight_id: highlightId } },
      body,
    }),
  );
}

export function deleteHighlight(highlightId: string) {
  return request(
    client.DELETE("/api/highlights/{highlight_id}", {
      params: { path: { highlight_id: highlightId } },
    }),
  );
}

export function sendChat(courseId: string, message: string, selection?: ChatSelectionIn) {
  return request(
    client.POST("/api/courses/{course_id}/chat", {
      params: { path: { course_id: courseId } },
      body: { message, selection: selection ?? null },
    }),
  );
}

export function getChatHistory(courseId: string) {
  return request(
    client.GET("/api/courses/{course_id}/chat", { params: { path: { course_id: courseId } } }),
  );
}
