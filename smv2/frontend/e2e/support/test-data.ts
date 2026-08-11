import { expect, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";

export const API_BASE = process.env.NEXT_PUBLIC_SMV2_API_URL ?? "http://127.0.0.1:8000";
const COURSE_PREFIX = "E2E disposable";
const PDF_BYTES = Buffer.from(
  "JVBERi0xLjQKMSAwIG9iago8PCAvVHlwZSAvQ2F0YWxvZyAvUGFnZXMgMiAwIFIgPj4KZW5kb2JqCjIgMCBvYmoKPDwgL1R5cGUgL1BhZ2VzIC9LaWRzIFszIDAgUl0gL0NvdW50IDEgPj4KZW5kb2JqCjMgMCBvYmoKPDwgL1R5cGUgL1BhZ2UgL1BhcmVudCAyIDAgUiAvTWVkaWFCb3ggWzAgMCAzMDAgMTQ0XSAvQ29udGVudHMgNCAwIFIgL1Jlc291cmNlcyA8PCAvRm9udCA8PCAvRjEgNSAwIFIgPj4gPj4gPj4KZW5kb2JqCjQgMCBvYmoKPDwgL0xlbmd0aCA2MyA+PgpzdHJlYW0KQlQKL0YxIDE4IFRmCjUwIDgwIFRkCihTb3VyY2VNaW5kIEUyRSBQREYgY291cnNlKSBUagpFVAplbmRzdHJlYW0KZW5kb2JqCjUgMCBvYmoKPDwgL1R5cGUgL0ZvbnQgL1N1YnR5cGUgL1R5cGUxIC9CYXNlRm9udCAvSGVsdmV0aWNhID4+CmVuZG9iagp4cmVmCjAgNgowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwMDkgMDAwMDAgbiAKMDAwMDAwMDA1OCAwMDAwMCBuIAowMDAwMDAwMTE1IDAwMDAwIG4gCjAwMDAwMDAyNDUgMDAwMDAgbiAKMDAwMDAwMDM1NyAwMDAwMCBuIAp0cmFpbGVyCjw8IC9Sb290IDEgMCBSIC9TaXplIDYgPj4Kc3RhcnR4cmVmCjQyNwpJSUVPRgo=",
  "base64",
);

export interface DisposableCourse {
  courseId: string;
  sectionId: string;
  title: string;
}

export function llm503Detail(message = "Structured test readiness failure") {
  return {
    detail: {
      code: "llm_readiness_unavailable",
      failure_category: "missing_credentials",
      message,
      remediation: "Open Settings and configure an AI provider.",
    },
  };
}

export function mockedSettings(model = "missing-model:latest") {
  return {
    provider: "ollama",
    model,
    credentials_present: { anthropic: false, ollama: true },
    credentials: {},
    rollout: { local_settings_enabled: true },
    readiness: {
      provider: "ollama",
      model,
      configured: true,
      available: false,
      capabilities: { completion: true, embeddings: true },
      last_checked_at: null,
      failure_category: "ollama_model_unavailable",
      remediation: "Select an installed Ollama model.",
    },
  };
}

export function attachPageErrorGuard(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  return errors;
}

export async function expectCleanPage(errors: string[]) {
  expect(errors, "no uncaught page errors or console errors").toEqual([]);
}

export async function createPdfCourse(request: APIRequestContext, testInfo: TestInfo): Promise<DisposableCourse> {
  const title = `${COURSE_PREFIX} ${testInfo.project.name} ${Date.now()}`;
  const create = await request.post(`${API_BASE}/api/courses`, {
    data: { title },
  });
  expect(create.ok(), await create.text()).toBeTruthy();
  const course = (await create.json()) as { id: string };
  testInfo.annotations.push({ type: "course_id", description: course.id });

  const upload = await request.post(`${API_BASE}/api/courses/${course.id}/assets`, {
    multipart: {
      file: {
        name: "e2e-default-pages.pdf",
        mimeType: "application/pdf",
        buffer: PDF_BYTES,
      },
    },
  });
  expect(upload.ok(), await upload.text()).toBeTruthy();

  const ingest = await request.post(`${API_BASE}/api/courses/${course.id}/ingest`);
  expect(ingest.ok(), await ingest.text()).toBeTruthy();
  const ingestBody = (await ingest.json()) as { job_id: string };
  await waitForJob(request, ingestBody.job_id);

  const sections = await request.get(`${API_BASE}/api/courses/${course.id}/sections`);
  expect(sections.ok(), await sections.text()).toBeTruthy();
  const sectionRows = (await sections.json()) as Array<{ id: string; kind?: string; asset_id?: string | null }>;
  const firstPdfSection = sectionRows.find((section) => section.kind === "content" && section.asset_id);
  expect(firstPdfSection, "uploaded PDF produced a content section with page provenance").toBeTruthy();

  return { courseId: course.id, sectionId: firstPdfSection!.id, title };
}

export async function deleteCourse(request: APIRequestContext, courseId: string | null | undefined) {
  if (!courseId) return;
  const response = await request.delete(`${API_BASE}/api/courses/${courseId}`);
  expect([204, 404], `cleanup status for ${courseId}`).toContain(response.status());
}

export async function cleanupDisposableCourses(request: APIRequestContext) {
  const response = await request.get(`${API_BASE}/api/courses`);
  expect(response.ok(), await response.text()).toBeTruthy();
  const courses = (await response.json()) as Array<{ id: string; title: string }>;
  for (const course of courses.filter((course) => course.title.startsWith(COURSE_PREFIX))) {
    await deleteCourse(request, course.id);
  }
}

export async function assertNoDisposableCourses(request: APIRequestContext) {
  const response = await request.get(`${API_BASE}/api/courses`);
  expect(response.ok(), await response.text()).toBeTruthy();
  const courses = (await response.json()) as Array<{ title: string }>;
  expect(courses.filter((course) => course.title.startsWith(COURSE_PREFIX))).toEqual([]);
}

async function waitForJob(request: APIRequestContext, jobId: string) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const response = await request.get(`${API_BASE}/api/jobs/${jobId}`);
    expect(response.ok(), await response.text()).toBeTruthy();
    const job = (await response.json()) as { status: string; error?: string | null };
    if (job.status === "succeeded") return;
    if (job.status === "failed") throw new Error(`job ${jobId} failed: ${job.error ?? "unknown error"}`);
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`job ${jobId} did not finish before timeout`);
}
