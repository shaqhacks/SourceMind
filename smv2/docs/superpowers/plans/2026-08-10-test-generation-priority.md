# Test Generation Priority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make explicitly requested chapter tests run before queued practice work, while chapter-test pages stay read-only until the learner explicitly starts practice generation.

**Architecture:** Keep the single durable worker, but centralize job ordering through one SQL priority constant consumed by the atomic claim query. Chapter-test creation resolves scope, reuses an active same-scope test job when one exists, otherwise atomically cancels matching queued practice jobs and deletes only the queued practice runs whose jobs were actually cancelled. The frontend treats `not_started` as no run, renders explicit section actions, and uses parent-to-child start command signals so each `InlinePracticeAssessment` owns its own POST, duplicate guard, local state, and polling.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, SQLite, pytest, Next.js 16, React 19, TypeScript, Vitest, Playwright.

## Global Constraints

- Opening a chapter-test page must be read-only and must not create practice-generation jobs.
- Students can generate practice for one section or explicitly generate all practice for the chapter.
- An explicitly requested chapter test runs before queued practice work.
- Starting a chapter test cancels queued practice jobs for the same chapter and deletes the matching queued `PracticeExtractionRun` rows; `not_started` is represented by no run row.
- Running and completed practice work is preserved in this version.
- The interface distinguishes queued work from active model thinking.
- Existing streaming and heartbeat behavior remains active after the test reaches execution.
- Duplicate user actions remain idempotent.
- No database priority column is added.
- Equal-priority jobs remain FIFO.
- Running practice jobs are not preempted or cancelled.
- No automatic-start prop is introduced on `InlinePracticeAssessment`.
- Parent bulk practice generation does not call `startPracticeAssessment()` directly.
- Every shell command in this workspace is prefixed with `rtk`.

---

## File Structure

- Modify `backend/app/jobs/worker.py`: central priority SQL constant consumed by `_CLAIM_SQL`.
- Modify `backend/tests/test_worker_claim.py`: test-over-practice priority and FIFO coverage.
- Modify `backend/app/services/tests_service.py`: active test-job idempotency, atomic queued-practice cancellation, run deletion, transactional job creation.
- Modify `backend/tests/test_quiz.py`: cancellation deletion, concurrency preservation, fresh practice restart, active test idempotency, terminal-job regeneration.
- Modify `frontend/components/chapter/practiceAssessmentState.ts`: explicit `not_started`, `startable`, and start eligibility helpers.
- Modify `frontend/components/chapter/InlinePracticeAssessment.tsx`: read-only mount, explicit per-section start, `startVersion` command signal, duplicate guard.
- Modify `frontend/__tests__/practice-assessment-state.test.ts`: state and summary coverage.
- Modify `frontend/__tests__/inline-practice-assessment.test.tsx`: GET-only mount, click guard, parent signal, polling after signal.
- Modify `frontend/components/chapter/ChapterTestClient.tsx`: per-section `startVersion` map and `Generate all practice` command dispatch.
- Modify `frontend/__tests__/chapter-test-client.test.tsx`: bulk signal coverage and queued-vs-thinking copy.
- Modify `frontend/components/jobs/GenerationProgress.tsx`: queued copy before execution progress.
- Modify `frontend/__tests__/generation-progress.test.tsx`: queued copy coverage.
- Modify `frontend/e2e/chapter-test-practice-recovery.spec.ts`: read-only open/refresh, individual/bulk generation, and queued test UX coverage.

### Task 1: Worker Priority TDD

**Files:**
- Modify: `backend/app/jobs/worker.py`
- Modify: `backend/tests/test_worker_claim.py`

**Interfaces:**
- Consumes: `Job.type`, `Job.status`, `Job.created_at`, and `claim_next_job(session: Session) -> Job | None`.
- Produces: `JOB_CLAIM_PRIORITY_SQL: Final[str]`, a single centralized SQL expression consumed directly by `_CLAIM_SQL`.
- Priority policy: `generate_test` priority `0`, all unlisted jobs priority `10`, `generate_practice_assessment` priority `20`.

- [ ] **Step 1: Write the failing priority tests**

Add these imports and helper to `backend/tests/test_worker_claim.py`:

```python
from datetime import timedelta

from app.db.models import Job, utcnow


def _queued_job(job_type: str, created_offset_seconds: int, payload: dict | None = None) -> Job:
    return Job(
        type=job_type,
        status="queued",
        payload=payload or {},
        created_at=utcnow() + timedelta(seconds=created_offset_seconds),
    )
```

Add these tests:

```python
def test_worker_claims_generate_test_before_older_practice_jobs(client):
    session = get_session()
    try:
        older_practice = _queued_job(
            "generate_practice_assessment",
            -30,
            {"course_id": "course-1", "section_id": "practice-1", "run_id": "run-1"},
        )
        test_job = _queued_job(
            "generate_test",
            0,
            {"course_id": "course-1", "section_ids": ["content-1"], "chapter_label": "Chapter 1"},
        )
        session.add_all([older_practice, test_job])
        session.commit()

        claimed = claim_next_job(session)

        assert claimed is not None
        assert claimed.id == test_job.id
        assert claimed.type == "generate_test"
        assert claimed.status == "running"
    finally:
        session.close()


def test_worker_preserves_fifo_inside_same_priority_class(client):
    session = get_session()
    try:
        first = _queued_job("generate_practice_assessment", -30, {"section_id": "practice-1"})
        second = _queued_job("generate_practice_assessment", -10, {"section_id": "practice-2"})
        session.add_all([first, second])
        session.commit()

        claimed = claim_next_job(session)

        assert claimed is not None
        assert claimed.id == first.id
        assert claimed.type == "generate_practice_assessment"
    finally:
        session.close()
```

- [ ] **Step 2: Run tests and confirm failure**

Working directory: `backend/`.

Run: `rtk uv run pytest -q tests/test_worker_claim.py -k "generate_test_before_older_practice_jobs or fifo_inside_same_priority_class"`

Expected: FAIL because the older practice job is claimed before the newer test job.

- [ ] **Step 3: Implement one consumed priority constant**

In `backend/app/jobs/worker.py`, add the import and constant:

```python
from typing import Final

JOB_CLAIM_PRIORITY_SQL: Final[str] = """
CASE
    WHEN type = 'generate_test' THEN 0
    WHEN type = 'generate_practice_assessment' THEN 20
    ELSE 10
END
"""
```

Build `_CLAIM_SQL` with that constant so no helper or duplicated CASE expression remains:

```python
_CLAIM_SQL = text(
    f"""
    UPDATE jobs
    SET status = 'running',
        lease_until = :lease_until,
        attempts = attempts + 1
    WHERE id = (
        SELECT id FROM jobs
        WHERE status = 'queued'
        ORDER BY {JOB_CLAIM_PRIORITY_SQL}, created_at
        LIMIT 1
    )
    AND status = 'queued'
    RETURNING id
    """
).bindparams(bindparam("lease_until", type_=DateTime()))
```

- [ ] **Step 4: Run priority regressions**

Working directory: `backend/`.

Run: `rtk uv run pytest -q tests/test_worker_claim.py tests/test_worker_loop.py tests/test_reconciler.py`

Expected: PASS. The worker claims tests ahead of older queued practice, preserves FIFO within the same priority class, and keeps existing lease/reconcile behavior.

- [ ] **Step 5: Commit worker priority**

```bash
rtk git add backend/app/jobs/worker.py backend/tests/test_worker_claim.py
rtk git commit -m "feat(jobs): prioritize interactive test generation"
```

### Task 2: Atomic Same-Chapter Queued Practice Cancellation/Test Creation TDD

**Files:**
- Modify: `backend/app/services/tests_service.py`
- Modify: `backend/tests/test_quiz.py`

**Interfaces:**
- Consumes: `jobs_service.create_job_in_session(session, job_type, payload) -> Job`, `PracticeExtractionRun.job_id`, `PracticeExtractionRun.status`, `Job.status`, and chapter-scoped `Section` rows.
- Produces: `_active_test_job_for_scope_in_session(session: Session, payload: dict[str, Any]) -> Job | None`.
- Produces: `_cancel_queued_practice_for_sections_in_session(session: Session, course_id: str, section_ids: list[str]) -> int`.
- Produces: `start_test_generation(...) -> str` that returns an existing active same-scope test job or atomically cancels queued practice, deletes cancelled runs, creates the new test job, and commits once.

- [ ] **Step 1: Write failing cancellation/deletion tests**

Add imports to `backend/tests/test_quiz.py`:

```python
import pytest

from app.db.models import PracticeExtractionRun, Section
from app.services import jobs_service, practice_service, tests_service
```

Add these helpers near `_make_questions()`:

```python
def _practice_section_by_title(client, course_id: str, title: str) -> dict:
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    return next(section for section in sections if section["title"] == title)


def _seed_practice_run_for_section(
    section_id: str,
    *,
    course_id: str,
    status: str,
    job_status: str,
    fingerprint_suffix: str,
) -> tuple[str, str]:
    session = get_session()
    try:
        job = Job(
            type="generate_practice_assessment",
            status=job_status,
            payload={"course_id": course_id, "section_id": section_id, "run_id": "seeded-later"},
            progress={"stage": "thinking", "message": "Preparing practice."},
            lease_until=utcnow() + timedelta(seconds=60) if job_status == "running" else None,
        )
        session.add(job)
        session.flush()
        run = PracticeExtractionRun(
            course_id=course_id,
            section_id=section_id,
            status=status,
            job_id=job.id,
            input_fingerprint=f"fingerprint-{section_id}-{fingerprint_suffix}",
            question_count=2 if status == "ready" else 0,
            error="learner-facing practice error" if status == "failed" else None,
        )
        session.add(run)
        session.flush()
        job.payload = {"course_id": course_id, "section_id": section_id, "run_id": run.id}
        session.commit()
        return job.id, run.id
    finally:
        session.close()
```

Add this test:

```python
def test_generate_test_cancels_queued_practice_by_deleting_runs_for_same_chapter(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    same_chapter = _practice_section_by_title(client, course_id, "0.1 Practice - Foundations")
    other_chapter = _practice_section_by_title(client, course_id, "0.2 Practice - Structures")
    cancelled_job_id, cancelled_run_id = _seed_practice_run_for_section(
        same_chapter["id"],
        course_id=course_id,
        status="queued",
        job_status="queued",
        fingerprint_suffix="queued-same",
    )
    other_job_id, other_run_id = _seed_practice_run_for_section(
        other_chapter["id"],
        course_id=course_id,
        status="queued",
        job_status="queued",
        fingerprint_suffix="queued-other",
    )
    running_job_id, running_run_id = _seed_practice_run_for_section(
        same_chapter["id"],
        course_id=course_id,
        status="queued",
        job_status="running",
        fingerprint_suffix="running-same",
    )
    stub_provider.responses = [
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model")
    ]

    resp = client.post(
        f"/api/courses/{course_id}/tests",
        json={"chapter_label": "Chapter 1: Foundations"},
    )

    assert resp.status_code == 202
    test_job_id = resp.json()["job_id"]
    session = get_session()
    try:
        cancelled_job = session.get(Job, cancelled_job_id)
        other_job = session.get(Job, other_job_id)
        other_run = session.get(PracticeExtractionRun, other_run_id)
        running_job = session.get(Job, running_job_id)
        running_run = session.get(PracticeExtractionRun, running_run_id)
        test_job = session.get(Job, test_job_id)

        assert cancelled_job.status == "cancelled"
        assert cancelled_job.progress is None
        assert cancelled_job.lease_until is None
        assert session.get(PracticeExtractionRun, cancelled_run_id) is None
        assert other_job.status == "queued"
        assert other_run.status == "queued"
        assert running_job.status == "running"
        assert running_run.status == "queued"
        assert test_job.status == "queued"
    finally:
        session.close()
```

- [ ] **Step 2: Write the failing fresh-run and stale-claim tests**

Add this test proving deletion recreates a fresh run/job on later POST:

```python
def test_practice_post_after_test_cancellation_creates_fresh_run_and_job(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    same_chapter = _practice_section_by_title(client, course_id, "0.1 Practice - Foundations")
    old_job_id, old_run_id = _seed_practice_run_for_section(
        same_chapter["id"],
        course_id=course_id,
        status="queued",
        job_status="queued",
        fingerprint_suffix="queued-before-test",
    )
    stub_provider.responses = [
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model")
    ]

    test_resp = client.post(
        f"/api/courses/{course_id}/tests",
        json={"chapter_label": "Chapter 1: Foundations"},
    )
    assert test_resp.status_code == 202
    practice_resp = client.post(
        f"/api/courses/{course_id}/sections/{same_chapter['id']}/practice-assessment"
    )

    assert practice_resp.status_code == 202
    body = practice_resp.json()
    assert body["run_id"] != old_run_id
    assert body["job_id"] != old_job_id
    session = get_session()
    try:
        assert session.get(PracticeExtractionRun, old_run_id) is None
        fresh_run = session.get(PracticeExtractionRun, body["run_id"])
        fresh_job = session.get(Job, body["job_id"])
        assert fresh_run is not None
        assert fresh_run.status == "queued"
        assert fresh_job is not None
        assert fresh_job.status == "queued"
    finally:
        session.close()
```

Add this test proving a stale candidate is not overwritten or deleted:

```python
def test_generate_test_preserves_practice_job_claimed_during_cancellation(
    client, ingest_course, monkeypatch, stub_provider
):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    same_chapter = _practice_section_by_title(client, course_id, "0.1 Practice - Foundations")
    claimed_job_id, claimed_run_id = _seed_practice_run_for_section(
        same_chapter["id"],
        course_id=course_id,
        status="queued",
        job_status="queued",
        fingerprint_suffix="claimed-race",
    )
    original_execute = tests_service.session_execute_returning_cancelled_job_ids

    def claim_before_update(session, statement):
        job = session.get(Job, claimed_job_id)
        assert job is not None
        job.status = "running"
        job.lease_until = utcnow() + timedelta(seconds=60)
        session.flush()
        return original_execute(session, statement)

    monkeypatch.setattr(
        tests_service,
        "session_execute_returning_cancelled_job_ids",
        claim_before_update,
    )
    stub_provider.responses = [
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model")
    ]

    resp = client.post(
        f"/api/courses/{course_id}/tests",
        json={"chapter_label": "Chapter 1: Foundations"},
    )

    assert resp.status_code == 202
    session = get_session()
    try:
        job = session.get(Job, claimed_job_id)
        run = session.get(PracticeExtractionRun, claimed_run_id)
        assert job.status == "running"
        assert job.lease_until is not None
        assert run is not None
        assert run.status == "queued"
        assert run.job_id == claimed_job_id
    finally:
        session.close()
```

- [ ] **Step 3: Write the failing test-generation idempotency tests**

Add active and terminal-scope tests:

```python
def test_generate_test_reuses_active_same_scope_job_without_repeated_cancellation(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    same_chapter = _practice_section_by_title(client, course_id, "0.1 Practice - Foundations")
    queued_practice_job_id, queued_run_id = _seed_practice_run_for_section(
        same_chapter["id"],
        course_id=course_id,
        status="queued",
        job_status="queued",
        fingerprint_suffix="idempotency-cancel-once",
    )
    stub_provider.responses = [
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model")
    ]

    first = client.post(
        f"/api/courses/{course_id}/tests",
        json={"chapter_label": "Chapter 1: Foundations"},
    )
    second = client.post(
        f"/api/courses/{course_id}/tests",
        json={"chapter_label": "Chapter 1: Foundations"},
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["job_id"] == first.json()["job_id"]
    session = get_session()
    try:
        assert session.query(Job).filter(Job.type == "generate_test").count() == 1
        assert session.get(Job, queued_practice_job_id).status == "cancelled"
        assert session.get(PracticeExtractionRun, queued_run_id) is None
    finally:
        session.close()


def test_generate_test_creates_new_job_after_same_scope_job_is_terminal(
    client, ingest_course, stub_provider
):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    stub_provider.responses = [
        CompletionResult(text=json.dumps(_make_questions()), input_tokens=1, output_tokens=1, model="stub-model")
    ]

    first = client.post(
        f"/api/courses/{course_id}/tests",
        json={"chapter_label": "Chapter 1: Foundations"},
    )
    session = get_session()
    try:
        first_job = session.get(Job, first.json()["job_id"])
        first_job.status = "succeeded"
        session.commit()
    finally:
        session.close()

    second = client.post(
        f"/api/courses/{course_id}/tests",
        json={"chapter_label": "Chapter 1: Foundations"},
    )

    assert second.status_code == 202
    assert second.json()["job_id"] != first.json()["job_id"]
```

- [ ] **Step 4: Write the failing rollback atomicity test**

Add this test:

```python
def test_generate_test_rolls_back_practice_cancellation_when_test_job_creation_fails(
    client, ingest_course, monkeypatch, stub_provider
):
    course_id, *_ = ingest_course("headings_no_bookmarks.pdf")
    same_chapter = _practice_section_by_title(client, course_id, "0.1 Practice - Foundations")
    queued_job_id, queued_run_id = _seed_practice_run_for_section(
        same_chapter["id"],
        course_id=course_id,
        status="queued",
        job_status="queued",
        fingerprint_suffix="rollback-create-test",
    )
    original_create_job_in_session = tests_service.jobs_service.create_job_in_session

    def fail_generate_test_job(session, job_type, payload):
        if job_type == "generate_test":
            raise RuntimeError("synthetic generate_test creation failure")
        return original_create_job_in_session(session, job_type, payload)

    monkeypatch.setattr(
        tests_service.jobs_service,
        "create_job_in_session",
        fail_generate_test_job,
    )

    with pytest.raises(RuntimeError, match="synthetic generate_test creation failure"):
        tests_service.start_test_generation(
            course_id,
            chapter_label="Chapter 1: Foundations",
        )

    session = get_session()
    try:
        queued_job = session.get(Job, queued_job_id)
        queued_run = session.get(PracticeExtractionRun, queued_run_id)
        assert queued_job is not None
        assert queued_job.status == "queued"
        assert queued_job.progress == {"stage": "thinking", "message": "Preparing practice."}
        assert queued_run is not None
        assert queued_run.status == "queued"
        assert queued_run.job_id == queued_job_id
        assert session.query(Job).filter(Job.type == "generate_test").count() == 0
    finally:
        session.close()
```

- [ ] **Step 5: Run tests and confirm failure**

Working directory: `backend/`.

Run: `rtk uv run pytest -q tests/test_quiz.py -k "cancels_queued_practice_by_deleting_runs or fresh_run or claimed_during_cancellation or reuses_active_same_scope or terminal or rolls_back_practice_cancellation"`

Expected: FAIL because cancellation mutates runs instead of deleting them, uses ORM-loaded job rows, and active test generation is not idempotent by scope.

- [ ] **Step 6: Implement active-job reuse**

In `backend/app/services/tests_service.py`, import:

```python
from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.db.models import Job, PracticeExtractionRun
```

Add helpers:

```python
ACTIVE_JOB_STATUSES = ("queued", "running")


def _test_scope_payload(
    course_id: str,
    resolved_section_ids: list[str] | None,
    chapter_label: str | None,
    course_learning_profile_id: str,
) -> dict[str, Any]:
    return {
        "course_id": course_id,
        "section_ids": resolved_section_ids,
        "chapter_label": chapter_label,
        "course_learning_profile_id": course_learning_profile_id,
    }


def _same_test_scope(payload: dict[str, Any] | None, expected: dict[str, Any]) -> bool:
    payload = payload or {}
    return (
        payload.get("course_id") == expected["course_id"]
        and payload.get("section_ids") == expected["section_ids"]
        and payload.get("chapter_label") == expected["chapter_label"]
        and payload.get("course_learning_profile_id") == expected["course_learning_profile_id"]
    )


def _active_test_job_for_scope_in_session(
    session: Session,
    expected_payload: dict[str, Any],
) -> Job | None:
    candidates = (
        session.query(Job)
        .filter(Job.type == "generate_test", Job.status.in_(ACTIVE_JOB_STATUSES))
        .order_by(Job.created_at.desc())
        .all()
    )
    for job in candidates:
        if _same_test_scope(job.payload, expected_payload):
            return job
    return None
```

In `start_test_generation()`, build `payload = _test_scope_payload(...)`, check `_active_test_job_for_scope_in_session(session, payload)` before cancelling practice, and return `active_job.id` immediately when found. Do not repeat queued-practice cancellation when returning an existing active job.

- [ ] **Step 7: Implement atomic conditional cancellation and run deletion**

Add this tiny wrapper so the stale-claim test can interpose without replacing SQL construction:

```python
def session_execute_returning_cancelled_job_ids(session: Session, statement) -> set[str]:
    return set(session.execute(statement).scalars().all())
```

Implement cancellation:

```python
def _cancel_queued_practice_for_sections_in_session(
    session: Session,
    course_id: str,
    section_ids: list[str],
) -> int:
    if not section_ids:
        return 0

    candidates = (
        session.query(PracticeExtractionRun.id, PracticeExtractionRun.job_id)
        .join(Job, Job.id == PracticeExtractionRun.job_id)
        .filter(
            PracticeExtractionRun.course_id == course_id,
            PracticeExtractionRun.section_id.in_(section_ids),
            PracticeExtractionRun.status == "queued",
            PracticeExtractionRun.job_id.is_not(None),
            Job.type == "generate_practice_assessment",
            Job.status == "queued",
        )
        .all()
    )
    candidate_job_ids = [job_id for _, job_id in candidates if job_id is not None]
    if not candidate_job_ids:
        return 0

    now = utcnow()
    cancelled_job_ids = session_execute_returning_cancelled_job_ids(
        session,
        sa_update(Job)
        .where(
            Job.id.in_(candidate_job_ids),
            Job.type == "generate_practice_assessment",
            Job.status == "queued",
        )
        .values(
            status="cancelled",
            result=None,
            progress=None,
            error=None,
            lease_until=None,
            cancel_requested_at=now,
        )
        .returning(Job.id),
    )
    if not cancelled_job_ids:
        return 0

    cancelled_run_ids = [
        run_id for run_id, job_id in candidates if job_id in cancelled_job_ids
    ]
    session.execute(
        sa_delete(PracticeExtractionRun).where(PracticeExtractionRun.id.in_(cancelled_run_ids))
    )
    return len(cancelled_run_ids)
```

Call `_cancel_queued_practice_for_sections_in_session()` and `jobs_service.create_job_in_session()` inside the same session before one `session.commit()`.

- [ ] **Step 8: Run backend regressions**

Working directory: `backend/`.

Run: `rtk uv run pytest -q tests/test_quiz.py tests/test_practice_api.py tests/test_practice_service.py tests/test_worker_claim.py`

Expected: PASS. Scoped active test requests reuse one job, terminal scoped jobs allow a later job, queued same-chapter practice runs are deleted only when their jobs were actually cancelled, running practice is preserved, and later practice POST creates a fresh queued run/job.

- [ ] **Step 9: Commit atomic cancellation and idempotency**

```bash
rtk git add backend/app/services/tests_service.py backend/tests/test_quiz.py
rtk git commit -m "feat(tests): atomically cancel queued chapter practice"
```

### Task 3: Lazy Per-Section Practice UI TDD

**Files:**
- Modify: `frontend/components/chapter/practiceAssessmentState.ts`
- Modify: `frontend/components/chapter/InlinePracticeAssessment.tsx`
- Modify: `frontend/__tests__/practice-assessment-state.test.ts`
- Modify: `frontend/__tests__/inline-practice-assessment.test.tsx`

**Interfaces:**
- Consumes: `getPracticeAssessment(courseId: string, sectionId: string)` and `startPracticeAssessment(courseId: string, sectionId: string)`.
- Produces: `PracticeSectionState` kind `"not_started"`.
- Produces: `isPracticeSectionStartable(state: PracticeSectionState | undefined) -> boolean`.
- Produces: `InlinePracticeAssessmentProps.startVersion?: number`; a larger value commands the child to start only when its current state is `not_started`.

- [ ] **Step 1: Write failing state-helper tests**

Add this test to `frontend/__tests__/practice-assessment-state.test.ts`:

```ts
it("reports not-started assessments as explicitly startable", () => {
  const state = practiceSectionStateFromAssessment(
    "section-1",
    makeAssessment({
      status: "not_started",
      questions: [],
      message: "Practice has not been generated yet.",
      run_id: null,
    }),
  );

  expect(state).toEqual({
    kind: "not_started",
    sectionId: "section-1",
    questionCount: 0,
    message: "Practice has not been generated yet.",
    errorDetail: null,
    retryKind: "start",
  });
  expect(isPracticeSectionStartable(state)).toBe(true);
  expect(isPracticeSectionStartable(generatingState("section-2"))).toBe(false);
  expect(isPracticeSectionStartable(readyState("section-3", 4))).toBe(false);
  expect(isPracticeSectionStartable(failedState("section-4", "restart"))).toBe(false);
});
```

Import `isPracticeSectionStartable` from `@/components/chapter/practiceAssessmentState`.

- [ ] **Step 2: Write failing read-only and per-section start tests**

In `frontend/__tests__/inline-practice-assessment.test.tsx`, update `practiceChild()` and `renderPracticeChild()` to accept `startVersion?: number`, then add:

```tsx
it("does not start generation when a not-started section mounts", async () => {
  const onStateChange = vi.fn();
  mockedGetPracticeAssessment.mockResolvedValue(
    ok(makeAssessment({ status: "not_started", questions: [], run_id: null })),
  );

  renderPracticeChild({ onStateChange });

  expect(await screen.findByRole("button", { name: "Generate practice questions" })).toBeEnabled();
  expect(mockedGetPracticeAssessment).toHaveBeenCalledWith("course-1", "section-1");
  expect(mockedStartPracticeAssessment).not.toHaveBeenCalled();
  expect(onStateChange).toHaveBeenCalledWith(
    expect.objectContaining({ kind: "not_started", sectionId: "section-1" }),
  );
});


it("starts only its own not-started section and guards duplicate clicks", async () => {
  const user = userEvent.setup();
  const started = deferred<ReturnType<typeof ok<PracticeAssessmentOut>>>();
  mockedGetPracticeAssessment.mockResolvedValue(
    ok(makeAssessment({ status: "not_started", questions: [], run_id: null })),
  );
  mockedStartPracticeAssessment.mockReturnValue(started.promise);

  renderPracticeChild({ sectionId: "section-explicit" });
  const button = await screen.findByRole("button", { name: "Generate practice questions" });

  await user.click(button);
  await user.click(button);
  started.resolve(
    ok(makeAssessment({ section_id: "section-explicit", status: "generating", questions: [] })),
  );
  await flushPracticeTasks();

  expect(mockedStartPracticeAssessment).toHaveBeenCalledTimes(1);
  expect(mockedStartPracticeAssessment).toHaveBeenCalledWith("course-1", "section-explicit");
  expect(await screen.findByRole("status")).toHaveTextContent(/preparing practice questions/i);
});
```

- [ ] **Step 3: Run focused tests and confirm failure**

Run: `rtk npm --prefix frontend test -- --run __tests__/practice-assessment-state.test.ts __tests__/inline-practice-assessment.test.tsx`

Expected: FAIL because the component either lacks `not_started` state handling or still auto-starts on mount.

- [ ] **Step 4: Implement explicit not-started state**

In `frontend/components/chapter/practiceAssessmentState.ts`, extend `PracticeSectionState`:

```ts
  | {
      kind: "not_started";
      sectionId: string;
      questionCount: 0;
      message: string | null;
      errorDetail: null;
      retryKind: "start";
    };
```

In `practiceSectionStateFromAssessment()`, add:

```ts
  if (assessment.status === "not_started") {
    return {
      kind: "not_started",
      sectionId,
      questionCount: 0,
      message: assessment.message ?? null,
      errorDetail: null,
      retryKind: "start",
    };
  }
```

Add:

```ts
export function isPracticeSectionStartable(state: PracticeSectionState | undefined) {
  return state?.kind === "not_started";
}
```

- [ ] **Step 5: Implement explicit child-owned start without an automatic-start prop**

In `frontend/components/chapter/InlinePracticeAssessment.tsx`, set props to:

```ts
interface InlinePracticeAssessmentProps {
  courseId: string;
  sectionId: string;
  retryVersion?: number;
  startVersion?: number;
  onStateChange?: (state: PracticeSectionState) => void;
}
```

Add refs:

```ts
const consumedStartVersionRef = useRef(startVersion);
const startingAssessmentRef = useRef(false);
```

For a `not_started` GET, only call `applyAssessment(result.data)`; do not call `startPracticeAssessment()`.

Add one shared start helper used by both the button and command signal:

```ts
const startNotStartedAssessment = useCallback(async () => {
  if (startingAssessmentRef.current) {
    return;
  }
  const currentState = currentSectionStateRef.current;
  if (currentState?.kind !== "not_started") {
    return;
  }

  startingAssessmentRef.current = true;
  setStarting(true);
  setLoadError(null);
  emitSectionState({
    kind: "generating",
    sectionId,
    questionCount: 0,
    message: "Preparing questions.",
    errorDetail: null,
    retryKind: null,
  });

  const startResult = await startPracticeAssessment(courseId, sectionId);
  startingAssessmentRef.current = false;
  if (!mountedRef.current) {
    return;
  }
  setStarting(false);

  if (!startResult.ok || !startResult.data) {
    const nextError = describeError(
      startResult.status,
      "Starting practice questions",
      startResult.error,
    );
    setLoadError(nextError);
    emitSectionState(practiceSectionStateFromLoadError(sectionId, nextError));
    return;
  }
  applyAssessment(startResult.data);
}, [applyAssessment, courseId, emitSectionState, sectionId]);
```

Consume parent commands:

```ts
useEffect(() => {
  if (startVersion === undefined || startVersion <= (consumedStartVersionRef.current ?? 0)) {
    return;
  }
  consumedStartVersionRef.current = startVersion;
  void startNotStartedAssessment();
}, [startNotStartedAssessment, startVersion]);
```

Render not-started:

```tsx
if (assessment?.status === "not_started") {
  return (
    <section className="rounded-md border border-border px-4 py-3">
      <Button onClick={() => void startNotStartedAssessment()} disabled={starting}>
        {starting ? "Starting..." : "Generate practice questions"}
      </Button>
    </section>
  );
}
```

- [ ] **Step 6: Run lazy-practice regressions**

Run: `rtk npm --prefix frontend test -- --run __tests__/practice-assessment-state.test.ts __tests__/inline-practice-assessment.test.tsx`

Expected: PASS. Mounting `not_started` performs one GET and no POST, the explicit section button posts once, and polling begins after the child applies a generating start response.

- [ ] **Step 7: Commit lazy per-section practice**

```bash
rtk git add frontend/components/chapter/practiceAssessmentState.ts frontend/components/chapter/InlinePracticeAssessment.tsx frontend/__tests__/practice-assessment-state.test.ts frontend/__tests__/inline-practice-assessment.test.tsx
rtk git commit -m "feat(practice): make section generation explicit"
```

### Task 4: Explicit Generate All Plus Queued/Thinking UX TDD

**Files:**
- Modify: `frontend/components/chapter/practiceAssessmentState.ts`
- Modify: `frontend/components/chapter/ChapterTestClient.tsx`
- Modify: `frontend/components/jobs/GenerationProgress.tsx`
- Modify: `frontend/__tests__/practice-assessment-state.test.ts`
- Modify: `frontend/__tests__/chapter-test-client.test.tsx`
- Modify: `frontend/__tests__/generation-progress.test.tsx`

**Interfaces:**
- Consumes: `isPracticeSectionStartable(state)`.
- Produces: `startable: number` in `PracticeSectionsSummary`.
- Produces: `practiceStartVersions: Record<string, number>` in `ChapterTestClient`.
- Produces: `Generate all practice` that increments `startVersion` only for current `not_started` child sections.
- Produces: queued test copy: `Queued` before `job.progress` exists; existing streamed progress copy after execution starts.

- [ ] **Step 1: Write failing summary test**

Add to `frontend/__tests__/practice-assessment-state.test.ts`:

```ts
it("counts explicit startable practice sections separately from loading work", () => {
  const summary = summarizePracticeSections(
    {
      "sec-start": {
        kind: "not_started",
        sectionId: "sec-start",
        questionCount: 0,
        message: "Practice has not been generated yet.",
        errorDetail: null,
        retryKind: "start",
      },
      "sec-ready": readyState("sec-ready", 2),
    },
    3,
  );

  expect(summary).toEqual({
    ready: 1,
    generating: 0,
    loading: 1,
    failed: 0,
    startable: 1,
    questions: 2,
    total: 3,
  });
});
```

- [ ] **Step 2: Write failing bulk-signal tests**

In `frontend/__tests__/chapter-test-client.test.tsx`, keep `InlinePracticeAssessment` mocked, but capture `startVersion` instead of mocking `startPracticeAssessment()` in the parent:

```ts
const inlinePracticeMock = vi.hoisted(() => ({
  callbacks: new Map<string, (state: PracticeSectionState) => void>(),
  retryVersions: new Map<string, number>(),
  startVersions: new Map<string, number>(),
}));
```

In the mocked component props:

```tsx
startVersion = 0,
```

and render:

```tsx
data-start-version={startVersion}
```

Add:

```tsx
it("commands all and only not-started children from the chapter action", async () => {
  const user = userEvent.setup();
  mockedListChapters.mockResolvedValue(
    ok([
      makeChapter({
        practice_section_ids: ["practice-start", "practice-ready", "practice-generating"],
      }),
    ]),
  );
  mockedGetSection.mockImplementation((sectionId: string) =>
    Promise.resolve(ok(makeSectionDetail({ id: sectionId }))),
  );
  mockedListTests.mockResolvedValue(ok([]));

  render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);
  await screen.findByRole("heading", { name: "Chapter 1 — Chapter test" });

  act(() => {
    inlinePracticeMock.callbacks.get("practice-start")?.({
      kind: "not_started",
      sectionId: "practice-start",
      questionCount: 0,
      message: null,
      errorDetail: null,
      retryKind: "start",
    });
    inlinePracticeMock.callbacks.get("practice-ready")?.(readyPracticeState("practice-ready", 3));
    inlinePracticeMock.callbacks.get("practice-generating")?.(generatingPracticeState("practice-generating"));
  });

  await user.click(await screen.findByRole("button", { name: "Generate all practice" }));
  await user.click(screen.getByRole("button", { name: "Generate all practice" }));

  expect(inlinePracticeMock.startVersions.get("practice-start")).toBe(1);
  expect(inlinePracticeMock.startVersions.get("practice-ready")).toBe(0);
  expect(inlinePracticeMock.startVersions.get("practice-generating")).toBe(0);
});
```

Add a child-level command test to `frontend/__tests__/inline-practice-assessment.test.tsx`:

```tsx
it("consumes a parent startVersion once and then owns POST state and polling", async () => {
  vi.useFakeTimers();
  mockedGetPracticeAssessment
    .mockResolvedValueOnce(ok(makeAssessment({ status: "not_started", questions: [], run_id: null })))
    .mockResolvedValueOnce(ok(makeAssessment({ status: "ready", questions: [makeQuestion()] })));
  mockedStartPracticeAssessment.mockResolvedValue(
    ok(makeAssessment({ status: "generating", questions: [], job_id: "job-practice" })),
  );

  const view = renderPracticeChild({ startVersion: 0 });
  await screen.findByRole("button", { name: "Generate practice questions" });
  view.rerender(practiceChild({ startVersion: 1 }));
  view.rerender(practiceChild({ startVersion: 1 }));

  await waitFor(() => expect(mockedStartPracticeAssessment).toHaveBeenCalledTimes(1));
  await advancePracticePoll();
  expect(await screen.findByText("Newton's second law")).toBeInTheDocument();
});
```

- [ ] **Step 3: Write failing queued-vs-thinking tests**

Add to `frontend/__tests__/generation-progress.test.tsx`:

```tsx
it("shows queued copy before execution progress starts", () => {
  render(
    <GenerationProgress
      job={{
        id: "job-queued",
        status: "running",
        progress: null,
      }}
      quiet={false}
    />,
  );

  expect(screen.getByText("Queued")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Queued");
  expect(screen.queryByText(/Thinking/)).not.toBeInTheDocument();
});
```

Add to `frontend/__tests__/chapter-test-client.test.tsx`:

```tsx
it("shows queued chapter-test copy until the job streams thinking progress", async () => {
  mockedListChapters.mockResolvedValue(ok([makeChapter()]));
  mockedGetSection.mockImplementation(mockGetSectionById);
  mockedListTests.mockResolvedValue(ok([]));
  mockedGenerateTest.mockResolvedValue(ok({ job_id: "job-queued-test" }));
  mockedGetJob.mockResolvedValue(
    ok(makeJob({ id: "job-queued-test", status: "running", progress: null })),
  );

  render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);
  await screen.findByRole("heading", { name: "Chapter 1 — Chapter test" });
  await userEvent.click(screen.getByRole("button", { name: "Take chapter test" }));

  expect(await screen.findByText("Queued")).toBeInTheDocument();
  expect(screen.queryByText(/Thinking/)).not.toBeInTheDocument();
});
```

- [ ] **Step 4: Run tests and confirm failure**

Run: `rtk npm --prefix frontend test -- --run __tests__/practice-assessment-state.test.ts __tests__/inline-practice-assessment.test.tsx __tests__/chapter-test-client.test.tsx __tests__/generation-progress.test.tsx`

Expected: FAIL because parent bulk generation either does not exist or POSTs directly, and queued copy is not distinct from progress copy.

- [ ] **Step 5: Implement parent-to-child start signals**

In `frontend/components/chapter/practiceAssessmentState.ts`, add `startable: number` to `PracticeSectionsSummary` and increment it only for `not_started`.

In `frontend/components/chapter/ChapterTestClient.tsx`, add:

```ts
const [practiceStartVersions, setPracticeStartVersions] = useState<Record<string, number>>({});
const [startingAllPractice, setStartingAllPractice] = useState(false);
```

Add handler:

```ts
const handleGenerateAllPractice = useCallback(() => {
  const startableIds = practiceSections
    .filter((section) => isPracticeSectionStartable(currentPracticeStates[section.id]))
    .map((section) => section.id);
  if (startableIds.length === 0 || startingAllPractice) {
    return;
  }

  setStartingAllPractice(true);
  setPracticeStartVersions((current) => {
    const next = { ...current };
    for (const sectionId of startableIds) {
      next[sectionId] = (next[sectionId] ?? 0) + 1;
    }
    return next;
  });
}, [currentPracticeStates, practiceSections, startingAllPractice]);
```

Clear the pending bulk flag when all commanded IDs leave `not_started`:

```ts
useEffect(() => {
  if (!startingAllPractice) {
    return;
  }
  const stillStartable = practiceSections.some((section) =>
    isPracticeSectionStartable(currentPracticeStates[section.id]),
  );
  if (!stillStartable) {
    setStartingAllPractice(false);
  }
}, [currentPracticeStates, practiceSections, startingAllPractice]);
```

Pass the command to each child:

```tsx
<InlinePracticeAssessment
  courseId={courseId}
  sectionId={section.id}
  retryVersion={practiceRetryVersions[section.id] ?? 0}
  startVersion={practiceStartVersions[section.id] ?? 0}
  onStateChange={handlePracticeSectionStateChange}
/>
```

Render:

```tsx
{practiceSummary.startable > 0 && (
  <Button size="sm" onClick={handleGenerateAllPractice} disabled={startingAllPractice}>
    {startingAllPractice ? "Starting practice..." : "Generate all practice"}
  </Button>
)}
```

- [ ] **Step 6: Implement queued test copy**

In `frontend/components/jobs/GenerationProgress.tsx`, derive one label for both the visible headline and the screen-reader live region:

```ts
const phaseLabel = job?.progress ? formatPhaseLabel(phase) : "Queued";
```

Use `phaseLabel` for the `headline` branch when `job.progress` is null and for the `role="status"` content. Leave streamed phases unchanged for non-null progress so a job with `{ progress: { stage: "thinking" } }` still announces and displays `Thinking`.

- [ ] **Step 7: Run frontend regressions**

Run: `rtk npm --prefix frontend test -- --run __tests__/practice-assessment-state.test.ts __tests__/inline-practice-assessment.test.tsx __tests__/chapter-test-client.test.tsx __tests__/generation-progress.test.tsx`

Expected: PASS. Bulk increments start versions for `not_started` children only, each child owns POST/polling, duplicate parent clicks do not duplicate child POSTs, progress-less test jobs say `Queued`, and streamed `thinking` still appears after execution starts.

- [ ] **Step 8: Commit bulk practice and queued UX**

```bash
rtk git add frontend/components/chapter/practiceAssessmentState.ts frontend/components/chapter/InlinePracticeAssessment.tsx frontend/components/chapter/ChapterTestClient.tsx frontend/components/jobs/GenerationProgress.tsx frontend/__tests__/practice-assessment-state.test.ts frontend/__tests__/inline-practice-assessment.test.tsx frontend/__tests__/chapter-test-client.test.tsx frontend/__tests__/generation-progress.test.tsx
rtk git commit -m "feat(chapter): command explicit bulk practice generation"
```

### Task 5: E2E/Regression/Build Verification

**Files:**
- Modify: `frontend/e2e/chapter-test-practice-recovery.spec.ts`
- Verify: backend, frontend unit, typecheck, lint, build, and E2E suites listed below.

**Interfaces:**
- Consumes: public chapter route `/course/[courseId]/chapter/[chapterLabel]/test`, API routes `/api/courses/{course_id}/sections/{section_id}/practice-assessment`, `/api/courses/{course_id}/tests`, and `/api/jobs/{job_id}/events`.
- Produces: E2E assertions that opening/refreshing creates zero practice jobs, individual and bulk practice actions create intended jobs once, queued same-chapter practice is cancelled by a test request, and streaming progress appears after the test is active.

- [ ] **Step 1: Extend E2E mocks for lazy practice and priority flow**

In `frontend/e2e/chapter-test-practice-recovery.spec.ts`, add a `not_started` route state and a test flow:

```ts
async function runLazyPracticeAndPriorityFlow({ page }: { page: Page }) {
  const guards = await preparePage(page);
  const posts = await installChapterRoutes(page, {
    practiceSectionIds: [readySectionId, generatingSectionId, failedSectionId],
    states: {
      [readySectionId]: assessment(readySectionId, "not_started", {
        message: "Practice has not been generated yet.",
        run_id: null,
      }),
      [generatingSectionId]: assessment(generatingSectionId, "not_started", {
        message: "Practice has not been generated yet.",
        run_id: null,
      }),
      [failedSectionId]: assessment(failedSectionId, "generating"),
    },
    onPracticePost: (sectionId) => assessment(sectionId, "generating"),
    onTestPost: () => {
      test.info().annotations.push({
        type: "priority",
        description: "backend test covers deletion of cancelled same-chapter queued practice runs",
      });
    },
  });

  await openChapterTest(page);
  expect(posts.practicePosts).toHaveLength(0);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: `${chapterLabel} — Chapter test` }),
  ).toBeVisible();
  expect(posts.practicePosts).toHaveLength(0);

  await page.getByRole("button", { name: "Generate practice questions" }).first().click();
  expect(posts.practicePosts.map((post) => post.sectionId)).toEqual([readySectionId]);

  await page.getByRole("button", { name: "Generate all practice" }).click();
  expect(posts.practicePosts.map((post) => post.sectionId)).toEqual([
    readySectionId,
    generatingSectionId,
  ]);

  await page.getByRole("button", { name: "Take chapter test" }).click();
  expect(posts.testPosts).toHaveLength(1);
  await expect(page.getByText("Queued")).toBeVisible();
  await expect(page.getByText(/Thinking|Generation/i)).toBeVisible();
  await expectNoCriticalViolations(page, "lazy-practice-priority");
  await expectNoPrivateOutput(page);
  await expectCleanGuards(guards);
}
```

Register:

```ts
test("chapter test page is read-only until explicit practice or test actions", async ({ page }) => {
  await runLazyPracticeAndPriorityFlow({ page });
});
```

- [ ] **Step 2: Run E2E and confirm any missing wiring fails**

Run: `rtk npm --prefix frontend run test:e2e -- chapter-test-practice-recovery.spec.ts generation-streaming.spec.ts`

Expected before final fixes: FAIL if route copy, button name, queue copy, child command handling, or bulk-start idempotency mismatch remains. Fix only mismatches in files listed in Tasks 3-5.

- [ ] **Step 3: Run focused backend verification**

Working directory: `backend/`.

Run: `rtk uv run pytest -q tests/test_worker_claim.py tests/test_quiz.py tests/test_practice_api.py tests/test_practice_service.py tests/test_reconciler.py tests/test_worker_loop.py`

Expected: PASS. Worker priority, active test-job idempotency, atomic cancellation, run deletion, fresh practice restart, running-job preservation, and restart reconciliation pass together.

- [ ] **Step 4: Run focused frontend verification**

Run: `rtk npm --prefix frontend test -- --run __tests__/practice-assessment-state.test.ts __tests__/inline-practice-assessment.test.tsx __tests__/chapter-test-client.test.tsx __tests__/generation-progress.test.tsx`

Expected: PASS. Read-only mount, explicit individual start, parent start command, explicit bulk start, queued copy, and thinking progress copy pass together.

- [ ] **Step 5: API schema note**

No API response schemas change in this plan, so schema regeneration is not required. If an implementer changes backend schemas while executing this plan, regenerate from `backend/`.

Working directory: `backend/`.

Run: `rtk uv run python -m app.export_openapi ../openapi.json`

Expected: PASS and `../openapi.json` updates only if backend schema output changed.

Run: `rtk npm --prefix frontend run gen:api`

Expected: PASS and `frontend/lib/api/schema.d.ts` matches `openapi.json`.

- [ ] **Step 6: Run static checks and build**

Run: `rtk npm --prefix frontend run typecheck`

Expected: PASS.

Run: `rtk npm --prefix frontend run lint`

Expected: PASS.

Run: `rtk npm --prefix frontend run build`

Expected: PASS.

- [ ] **Step 7: Run full app build**

Working directory: repository root.

Run: `rtk ./build.sh`

Expected: PASS.

- [ ] **Step 8: Run final E2E verification**

Run: `rtk npm --prefix frontend run test:e2e -- chapter-test-practice-recovery.spec.ts generation-streaming.spec.ts`

Expected: PASS. Opening and refreshing the chapter-test page creates zero practice POSTs, individual and bulk practice buttons create only intended practice POSTs once, chapter-test request is acknowledged as queued, and streamed progress appears after execution begins.

- [ ] **Step 9: Commit verification coverage**

```bash
rtk git add frontend/e2e/chapter-test-practice-recovery.spec.ts openapi.json frontend/lib/api/schema.d.ts
rtk git commit -m "test(chapter): verify lazy practice and test priority"
```

## Self-Review

**Spec coverage:** Covered. Task 1 implements deterministic test-over-practice priority without a dead helper or duplicated CASE policy. Task 2 implements active test idempotency, atomic conditional queued-practice cancellation, deletion of matching queued practice runs, stale-claim preservation, fresh practice POST recreation, and terminal-job regeneration. Task 3 makes page mount read-only and adds child-owned explicit starts without an automatic-start prop. Task 4 adds parent-to-child bulk command signals plus queued-vs-thinking copy. Task 5 verifies backend, frontend, streaming, and user-perspective flows.

**Exact commands and working directories:** Backend `uv` commands state `Working directory: backend/` and use `tests/...` paths. Root-level frontend commands use `rtk npm --prefix frontend ...`. Full app verification includes `rtk ./build.sh` from repository root. The optional OpenAPI command uses `rtk uv run python -m app.export_openapi ../openapi.json` from `backend/`.

**Red-flag scan:** The plan uses exact files, function names, commands, expected failures, expected passes, and commit commands. It contains no deferred implementation markers.

**Type consistency:** `PracticeSectionState.kind` values are `loading`, `not_started`, `generating`, `ready`, and `failed`; `retryKind` values are `start`, `reload`, `restart`, and `null`; `InlinePracticeAssessment` accepts `startVersion?: number`; `PracticeSectionsSummary.startable` is introduced before `ChapterTestClient` consumes it. Backend helpers use `Session`, `Job`, `PracticeExtractionRun`, `jobs_service.create_job_in_session()`, `sa_update()`, and `sa_delete()`.

## Risks

- The stale-claim regression uses a small wrapper around `session.execute(...returning())` so the test can interpose. If implementers choose a different test seam, they must keep the same behavioral assertion: a job claimed after candidate selection is not overwritten and its run is not deleted.
- The active test-job idempotency key compares JSON payload fields in Python because this plan avoids a new database index or schema change. If payload shape changes later, the helper tests should fail before duplicate active jobs return.
- Active same-scope test idempotency covers sequential/repeated requests in this single-process local version. It is not a multi-process concurrent uniqueness guarantee because this plan adds no database uniqueness constraint or cross-process lock.
- Playwright route timing can be sensitive around fake `EventSource`; keep the existing E2E guard patterns and avoid real provider/Ollama calls.
