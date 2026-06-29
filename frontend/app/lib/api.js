export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export async function getText(path) {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!res.ok) {
    const err = new Error(res.statusText);
    err.status = res.status;
    throw err;
  }
  return res.text();
}

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

// --- Library API client (new /library/* endpoints) ---
export const library = {
  // Upload PDFs to create a new course
  uploadPdfs: (formData) => postForm("/library/uploads", formData),

  // List all courses
  listCourses: () => getJson("/library/courses"),

  // Get a single course (returns { course, plan, chapters })
  getCourse: (id) => getJson(`/library/courses/${encodeURIComponent(id)}`),

  // Delete a course and all its data
  deleteCourse: (id) => deleteJson(`/library/courses/${encodeURIComponent(id)}`),

  // Get the course study plan
  getPlan: (id) => getJson(`/library/courses/${encodeURIComponent(id)}/plan`),

  // Approve the study plan
  approvePlan: (id) => postJson(`/library/courses/${encodeURIComponent(id)}/plan/approve`, {}),

  // Trigger content generation
  generate: (id) => postJson(`/library/courses/${encodeURIComponent(id)}/generate`, {}),

  // Get a specific chapter
  getChapter: (id, sid) =>
    getJson(`/library/courses/${encodeURIComponent(id)}/chapters/${encodeURIComponent(sid)}`),

  // Mark chapter progress
  setProgress: (id, sid, completed) =>
    postJson(`/library/courses/${encodeURIComponent(id)}/chapters/${encodeURIComponent(sid)}/progress`, { completed }),

  // Chat within a chapter
  chat: (id, sid, question) =>
    postJson(`/library/courses/${encodeURIComponent(id)}/chapters/${encodeURIComponent(sid)}/chat`, { question }),

  // Get due review cards for a course
  dueReviews: (id) => getJson(`/library/courses/${encodeURIComponent(id)}/reviews/due`),

  // Get due review cards across ALL courses (already joined to q/a + course_title)
  dueReviewsAll: () => getJson("/library/reviews/due"),

  // Grade a review card
  gradeReview: (id, { section_id, card_index, correct }) =>
    postJson(`/library/courses/${encodeURIComponent(id)}/reviews/grade`, { section_id, card_index, correct }),

  // Notification summary (due review count + per-course status)
  notifications: () => getJson("/library/notifications"),

  // Returns the absolute URL for downloading the Anki TSV file (use as href)
  ankiTsvUrl: (id) => `${API_URL}/library/courses/${encodeURIComponent(id)}/anki.tsv`,

  // Fetches the Anki TSV file content as text
  getAnkiTsv: (id) => getText(`/library/courses/${encodeURIComponent(id)}/anki.tsv`),
};
