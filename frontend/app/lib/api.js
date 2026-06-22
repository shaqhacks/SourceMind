export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

async function asJson(res) {
  const text = await res.text();
  const body = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = body && body.detail ? body.detail : res.statusText;
    const message = typeof detail === "string" ? detail : JSON.stringify(detail);
    const err = new Error(message);
    err.status = res.status;
    throw err;
  }
  return body;
}

function qs(params) {
  const usable = Object.entries(params || {}).filter(([, v]) => v !== undefined && v !== null);
  if (!usable.length) return "";
  return "?" + usable.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");
}

export async function getJson(path) {
  return asJson(await fetch(`${API_URL}${path}`, { cache: "no-store" }));
}

export async function postJson(path, payload) {
  return asJson(
    await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

export async function putJson(path, payload) {
  return asJson(
    await fetch(`${API_URL}${path}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  );
}

export async function deleteJson(path) {
  return asJson(await fetch(`${API_URL}${path}`, { method: "DELETE" }));
}

export async function postForm(path, formData) {
  return asJson(await fetch(`${API_URL}${path}`, { method: "POST", body: formData }));
}

// --- Named endpoint helpers (bind to the backend contract) ---
export const api = {
  health: () => getJson("/health"),

  // Courses
  listCourses: (includeArchived = false) => getJson(`/courses${qs({ include_archived: includeArchived })}`),
  getCourse: (id) => getJson(`/courses/${encodeURIComponent(id)}`),
  getOutline: (id) => getJson(`/courses/${encodeURIComponent(id)}/outline`),
  putOutline: (id, chapters) => putJson(`/courses/${encodeURIComponent(id)}/outline`, { chapters }),
  archiveCourse: (id) => postJson(`/courses/${encodeURIComponent(id)}/archive`, {}),
  restoreCourse: (id) => postJson(`/courses/${encodeURIComponent(id)}/restore`, {}),
  deleteCourse: (id) => deleteJson(`/courses/${encodeURIComponent(id)}`),
  generateCourse: (id) => postJson(`/courses/${encodeURIComponent(id)}/generate`, {}),
  uploadCoursePdfs: (formData) => postForm("/courses/uploads", formData),
  regenerateSection: (id, sid) =>
    postJson(`/courses/${encodeURIComponent(id)}/sections/${encodeURIComponent(sid)}/regenerate`, {}),
  getSection: (id, sid) =>
    getJson(`/courses/${encodeURIComponent(id)}/sections/${encodeURIComponent(sid)}`),
  chatSection: (id, sid, question) =>
    postJson(`/courses/${encodeURIComponent(id)}/sections/${encodeURIComponent(sid)}/chat`, { question }),
  gradeCheck: (id, sid, checkId, answer, confidence) =>
    postJson(
      `/courses/${encodeURIComponent(id)}/sections/${encodeURIComponent(sid)}/checks/${encodeURIComponent(checkId)}/grade`,
      { answer, confidence }
    ),
  submitQuiz: (id, sid, answers, confidence) =>
    postJson(`/courses/${encodeURIComponent(id)}/sections/${encodeURIComponent(sid)}/quiz/submit`, {
      answers,
      confidence,
    }),
  notifications: (includeUpcoming = true) =>
    getJson(`/courses/notifications${qs({ include_upcoming: includeUpcoming })}`),
  dueReviews: (includeUpcoming = false) => getJson(`/courses/reviews/due${qs({ include_upcoming: includeUpcoming })}`),
  courseDueReviews: (id, includeUpcoming = false) =>
    getJson(`/courses/${encodeURIComponent(id)}/reviews/due${qs({ include_upcoming: includeUpcoming })}`),

  // Ingest
  uploadSource: ({ source_type, content, title }) => postJson("/upload/source", { source_type, content, title }),
  uploadSubjectPdf: (formData) => postForm("/upload/pdf", formData),

  // Subjects (legacy, read-only on dashboard)
  listSubjects: () => getJson("/subjects"),
  getDashboard: () => getJson("/dashboard"),
};
