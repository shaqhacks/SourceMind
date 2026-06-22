# Comprehensive SourceMind Frontend

Build a comprehensive Next.js (App Router, JS) frontend in `frontend/` that covers
the spec (`docs/sourcemind-first-draft.md`) and binds to the live FastAPI backend.
API base via `NEXT_PUBLIC_API_URL` (default http://127.0.0.1:8000). Primary system =
Courses (`/courses/*`): upload → approve outline → generate book → study section →
checks/quiz → spaced review. Subjects (`/subjects`) shown read-only on the dashboard.

Verification per story: `npm run build` green (no type/lint errors) + the page binds
to the exact backend field names from the API contract. Final story gated behind
ai-slop-cleaner + verification + code-review APPROVE.

Key contract:
- GET /courses -> {courses:[{course_id,title,status,chapters,competencies,generation:{status,total_sections,completed_sections,failed_sections,next_retry_at,last_error}}]}
- POST /courses/uploads (multipart files+title) -> {course_id,title,status,chapters_count,sections_count}
- GET /courses/{id} -> CourseDocument; GET/PUT /courses/{id}/outline (chapters[])
- POST /courses/{id}/generate -> CourseDocument; POST /courses/{id}/sections/{sid}/regenerate
- GET /courses/{id}/sections/{sid} -> {course_id,course_title,section:SectionLesson,competencies:[CourseCompetency]}
- POST /courses/{id}/sections/{sid}/chat {question} -> {answer,support_status,source_refs,created_at}
- POST /courses/{id}/sections/{sid}/checks/{cid}/grade {answer,confidence(1-6)} -> {score,passed,feedback}
- POST /courses/{id}/sections/{sid}/quiz/submit {answers:{cid:ans},confidence} -> {score,feedback,results}
- GET /courses/reviews/due?include_upcoming -> {items:[{course_id,course_title,competency_id,competency_title,section_id,section_number,section_title,mastery_percent,last_score,next_review_at,due,reason}],due_count,upcoming_count}
- POST /upload/source {source_type,content,title?} -> {title,source_type,competencies_count,chapters_count,rubric_passed,rubric_total}
- POST /upload/pdf (multipart) -> {subject_id,...,competencies_count,quotes_count,status}
- GET /subjects -> {subjects:[id]}; GET /dashboard -> DashboardResponse; GET /health

SectionLesson fields: learning_objectives[], concepts[{title,explanation,source_refs}],
lesson_blocks[{kind,title,body,source_refs}], worked_examples[{title,prompt,steps}],
checks[{id,kind,prompt,choices,last_score,completed}], mastery_quiz[{id,kind,prompt}],
source_spans[{source_name,page_start,page_end,text}], prerequisites[], completed, status.
CourseCompetency: {id,title,description,level,prerequisite_ids,mastery:{mastery_percent,...}}.
