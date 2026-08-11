"""Quiz (Test deck / TestAttempt) generation, retrieval, grading, listing,
and retaking. Business logic for generate_test/get_test/submit_test/
list_tests/retake_test — routers only do existence/state checks and
delegate here.

ADR-022 deck/attempt split: Test holds the generated questions (created
once, by generate_test); TestAttempt holds only one attempt's own
answers/results/score. Retaking a test (retake_test) creates a new
TestAttempt against the SAME Test, zero further LLM calls.

get_test hides correct_index/explanation while the attempt is ungraded
(score is None) — a learner must not be able to peek at answers by
reading the raw attempt before submitting.

ADR-017/ADR-022: submit_test turns every question into a flashcard —
missed -> due now (as before ADR-022), correct -> seeded as a successful
review so the whole tested deck enters Anki rotation with the test as its
first review event. See _resolve_missed_card_section_id/_seed_missed_card/
_seed_correct_card for the exact policy, including the cramming guard.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.db.identity import card_id_for
from app.db.models import (
    Card,
    Course,
    CourseLearningProfile,
    Job,
    PracticeExtractionRun,
    ReviewState,
    Section,
    Test,
    TestAttempt,
    ensure_utc,
    utcnow,
)
from app.services import (
    evidence_items_service,
    evidence_service,
    jobs_service,
    learner_context,
    llm_readiness_service,
)
from app.services.srs_service import DEFAULT_EASE, GOOD, schedule_next

ACTIVE_JOB_STATUSES = ("queued", "running")


class CourseNotFoundError(ValueError):
    pass


class ChapterNotFoundError(ValueError):
    pass


class TestAlreadySubmittedError(ValueError):
    pass


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


def _canonical_section_ids(
    session: Session,
    course_id: str,
    section_ids: list[str] | None,
) -> list[str] | None:
    if section_ids is None:
        return None
    if not section_ids:
        return []

    requested = set(section_ids)
    ordered_ids = [
        section_id
        for (section_id,) in session.query(Section.id)
        .filter(Section.course_id == course_id, Section.id.in_(requested))
        .order_by(Section.order_index)
        .all()
    ]
    matched_ids = set(ordered_ids)
    missing_ids = [section_id for section_id in section_ids if section_id not in matched_ids]
    return ordered_ids + missing_ids


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


def session_execute_returning_cancelled_job_ids(session: Session, statement) -> set[str]:
    return set(session.execute(statement).scalars().all())


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
        sa_delete(PracticeExtractionRun).where(
            PracticeExtractionRun.id.in_(cancelled_run_ids)
        )
    )
    return len(cancelled_run_ids)


def start_test_generation(
    course_id: str,
    section_ids: list[str] | None = None,
    chapter_label: str | None = None,
    *,
    learner_id: str = learner_context.LEGACY_LOCAL_LEARNER_ID,
) -> str:
    session = get_session()
    try:
        course = session.get(Course, course_id)
        if course is None:
            raise CourseNotFoundError(f"course not found: {course_id}")

        resolved_section_ids = section_ids
        if chapter_label is not None:
            # Practice + content sections only — never an answer key (see
            # run_test_generation's whole-course fallback for the same
            # reasoning: a printed answer key in the prompt invites the
            # model to copy its numbering instead of writing real questions).
            resolved_section_ids = [
                s.id
                for s in session.query(Section)
                .filter(
                    Section.course_id == course_id,
                    Section.chapter_label == chapter_label,
                    Section.kind != "answers",
                )
                .order_by(Section.order_index)
                .all()
            ]
            if not resolved_section_ids:
                raise ChapterNotFoundError(
                    f"no practice/content sections found for chapter {chapter_label!r}"
                )
        else:
            resolved_section_ids = _canonical_section_ids(
                session,
                course_id,
                resolved_section_ids,
            )
        course_profile = learner_context.ensure_course_learning_profile(
            session, learner_id, course_id
        )
        session.flush()
        payload = _test_scope_payload(
            course_id,
            resolved_section_ids,
            chapter_label,
            course_profile.id,
        )
        active_job = _active_test_job_for_scope_in_session(session, payload)
        if active_job is not None:
            return active_job.id
        llm_readiness_service.assert_ready_for_generation()
        _cancel_queued_practice_for_sections_in_session(
            session,
            course_id,
            resolved_section_ids or [],
        )
        job = jobs_service.create_job_in_session(session, "generate_test", payload)
        session.commit()
        return job.id
    finally:
        session.close()


def _get_owned_attempt(session, attempt_id: str, learner_id: str) -> TestAttempt | None:
    return (
        session.query(TestAttempt)
        .join(
            CourseLearningProfile,
            CourseLearningProfile.id == TestAttempt.course_learning_profile_id,
        )
        .filter(TestAttempt.id == attempt_id, CourseLearningProfile.learner_id == learner_id)
        .one_or_none()
    )


def get_test(
    attempt_id: str, *, learner_id: str = learner_context.LEGACY_LOCAL_LEARNER_ID
) -> dict[str, Any] | None:
    session = get_session()
    try:
        attempt = _get_owned_attempt(session, attempt_id, learner_id)
        if attempt is None:
            return None
        test = session.get(Test, attempt.test_id)

        if attempt.score is None:
            visible_questions = [{"question": q["question"], "choices": q["choices"]} for q in test.questions]
        else:
            visible_questions = test.questions

        return {
            "id": attempt.id,
            "test_id": test.id,
            "course_id": attempt.course_id,
            "chapter_label": test.chapter_label,
            "score": attempt.score,
            "questions": visible_questions,
            "answers": attempt.answers,
            "results": attempt.results,
            "created_at": attempt.created_at,
        }
    finally:
        session.close()


def retake_test(
    test_id: str, *, learner_id: str = learner_context.LEGACY_LOCAL_LEARNER_ID
) -> str | None:
    """Creates a new TestAttempt against test_id's EXISTING, already-
    generated questions — zero LLM calls (ADR-022). Returns the new
    attempt's id, or None if the test doesn't exist.
    """
    session = get_session()
    try:
        test = session.get(Test, test_id)
        if test is None:
            return None
        course_profile = learner_context.ensure_course_learning_profile(
            session, learner_id, test.course_id
        )
        attempt = TestAttempt(
            test_id=test.id,
            course_id=test.course_id,
            course_learning_profile_id=course_profile.id,
        )
        session.add(attempt)
        session.commit()
        return attempt.id
    finally:
        session.close()


def _resolve_missed_card_section_id(session, test: Test) -> str | None:
    """Where a card built from one of this test's questions should live:
    the test's chapter's first practice section if one exists, else that
    chapter's first section of any kind, else the test's own
    (single-section-mode) section_id, else the course's first section —
    always resolving to SOMETHING if the course has any section at all.
    """
    if test.chapter_label is not None:
        chapter_sections = (
            session.query(Section)
            .filter(Section.course_id == test.course_id, Section.chapter_label == test.chapter_label)
            .order_by(Section.order_index)
            .all()
        )
        practice = next((s for s in chapter_sections if s.kind == "practice"), None)
        if practice is not None:
            return practice.id
        if chapter_sections:
            return chapter_sections[0].id

    if test.section_id is not None:
        return test.section_id

    first_section = (
        session.query(Section)
        .filter(Section.course_id == test.course_id)
        .order_by(Section.order_index)
        .first()
    )
    return first_section.id if first_section is not None else None


def _build_card_content(question: dict[str, Any]) -> tuple[str, str]:
    choices_md = "\n".join(f"- {c}" for c in question["choices"])
    front_md = f"{question['question']}\n\n{choices_md}"

    correct_text = question["choices"][question["correct_index"]]
    explanation = (question.get("explanation") or "").strip()
    back_md = f"{correct_text}\n\n{explanation}" if explanation else correct_text
    return front_md, back_md


def _ensure_card(session, course_id: str, section_id: str, question: dict[str, Any]) -> tuple[str, bool]:
    """Every question becomes a content-addressed card (ADR-022), whether
    missed or correct — dedup as before (same front/back -> same id,
    whether generated by card generation or a quiz question). Returns
    (card_id, created_just_now).
    """
    front_md, back_md = _build_card_content(question)
    card_id = card_id_for(section_id, front_md, back_md)

    card = session.get(Card, card_id)
    if card is not None:
        return card_id, False

    position = session.query(Card).filter(Card.section_id == section_id).count()
    session.add(
        Card(
            id=card_id,
            course_id=course_id,
            section_id=section_id,
            front_md=front_md,
            back_md=back_md,
            position=position,
        )
    )
    return card_id, True


def _seed_missed_card(session, course_learning_profile_id: str, card_id: str) -> None:
    """A miss is evidence the card needs review NOW, not a formal SM-2
    lapse — only due_at moves. A brand-new card (just created by
    _ensure_card, no ReviewState row at all) needs no action here: the
    review queue already treats "no ReviewState" as "new" and thus due,
    same convention card generation itself relies on. ease/interval/reps
    on an EXISTING card are left untouched — a genuine Again grade from
    the review queue is what should ever reduce ease or count as a lapse,
    not a test miss.
    """
    review_state = session.get(ReviewState, (course_learning_profile_id, card_id))
    if review_state is not None:
        review_state.due_at = utcnow()


def _seed_correct_card(
    session,
    course_learning_profile_id: str,
    card_id: str,
    course_id: str,
    review_state: ReviewState | None,
) -> None:
    """ADR-022: a correct answer is real review evidence, not a freebie —
    the whole tested deck should enter Anki rotation with the test as its
    first review event, but a card someone is deliberately CRAMMING (not
    yet due) must not get credit it didn't earn, or a learner could farm
    early advancement by re-taking a test on cards they only just saw.

    Brand-new card (no ReviewState at all): seed one successful review via
    the REAL schedule_next(GOOD, ...) from the bootstrap state — identical
    to a genuine first Good grade from the review queue (baseline 1 day,
    reps becomes 1, due tomorrow).

    Existing card: only seed if it was ACTUALLY due or new right now (its
    OWN due_at <= now) — schedule_next(GOOD, ...) from its current state,
    same as a real review-queue grade. If it's not yet due, leave it
    completely untouched: the test answered it correctly, but that's not
    a real review opportunity if the card wasn't due to be seen yet — the
    cramming guard this rule exists for.
    """
    if review_state is None:
        result = schedule_next(GOOD, interval_days=0.0, ease=DEFAULT_EASE, reps=0)
        session.add(
            ReviewState(
                course_learning_profile_id=course_learning_profile_id,
                card_id=card_id,
                course_id=course_id,
                due_at=result.due_at,
                interval_days=result.interval_days,
                ease=result.ease,
                reps=result.reps,
                lapses=result.lapses_delta,
                last_grade=GOOD,
            )
        )
        return

    if ensure_utc(review_state.due_at) > utcnow():
        return  # cramming guard: not yet due, leave untouched

    result = schedule_next(
        GOOD, interval_days=review_state.interval_days, ease=review_state.ease, reps=review_state.reps
    )
    review_state.due_at = result.due_at
    review_state.interval_days = result.interval_days
    review_state.ease = result.ease
    review_state.reps = result.reps
    review_state.lapses += result.lapses_delta
    review_state.last_grade = GOOD


def submit_test(
    attempt_id: str,
    answers: list[int],
    *,
    learner_id: str = learner_context.LEGACY_LOCAL_LEARNER_ID,
) -> dict[str, Any] | None:
    session = get_session()
    try:
        attempt = _get_owned_attempt(session, attempt_id, learner_id)
        if attempt is None:
            return None
        if attempt.score is not None:
            raise TestAlreadySubmittedError(f"test attempt {attempt_id} already submitted")

        test = session.get(Test, attempt.test_id)
        questions = test.questions
        target_section_id = _resolve_missed_card_section_id(session, test)

        results = []
        correct_count = 0
        # added_card_ids keeps its pre-ADR-022 meaning exactly (missed-
        # question cards only) — an existing frontend surface already
        # reads this as "cards that need your attention now," and every
        # missed card is exactly that; a correct answer's seeded review is
        # NOT due now (1 day+ out) so it would be a misleading inclusion
        # here. due_now_count is a new, separate count of the same set —
        # kept as its own field because a MISSED card is the only outcome
        # that ever produces a right-now-due card in this design, so the
        # two numbers are equal in practice; this is intentional, not a
        # bug, and documented since the redundancy could look like one.
        added_card_ids: list[str] = []
        due_now_count = 0
        for i, q in enumerate(questions):
            your_answer = answers[i] if i < len(answers) else None
            is_correct = your_answer == q["correct_index"]
            if is_correct:
                correct_count += 1

            if target_section_id is not None:
                card_id, created_now = _ensure_card(session, attempt.course_id, target_section_id, q)
                if is_correct:
                    review_state = (
                        None
                        if created_now
                        else session.get(
                            ReviewState, (attempt.course_learning_profile_id, card_id)
                        )
                    )
                    _seed_correct_card(
                        session,
                        attempt.course_learning_profile_id,
                        card_id,
                        attempt.course_id,
                        review_state,
                    )
                else:
                    if not created_now:
                        _seed_missed_card(
                            session, attempt.course_learning_profile_id, card_id
                        )
                    added_card_ids.append(card_id)
                    due_now_count += 1

            results.append(
                {
                    "correct": is_correct,
                    "correct_index": q["correct_index"],
                    "explanation": q.get("explanation", ""),
                    "your_answer": your_answer,
                }
            )
            evidence_item = evidence_service.find_item(
                session,
                item_type="quiz_question",
                source_record_id=test.id,
                source_index=i,
            )
            if evidence_item is None:
                evidence_item = evidence_items_service.snapshot_item(
                    session,
                    course_id=attempt.course_id,
                    item_type="quiz_question",
                    source_record_id=test.id,
                    source_index=i,
                    content={
                        "question": q["question"],
                        "choices": q["choices"],
                        "correct_index": q["correct_index"],
                        "explanation": q.get("explanation", ""),
                    },
                    source_ref=test.chapter_label or test.section_id,
                    prompt_version=test.prompt_version,
                    model=test.model,
                )
            evidence_service.record_event(
                session,
                course_learning_profile_id=attempt.course_learning_profile_id,
                evidence_item=evidence_item,
                channel="quiz",
                normalized_outcome=1.0 if is_correct else 0.0,
                raw_result={
                    "correct": is_correct,
                    "selected_index": your_answer,
                    "correct_index": q["correct_index"],
                },
                source_event_key=f"test_attempt:{attempt.id}:question:{i}",
                event_at=utcnow(),
                attempt_id=attempt.id,
            )

        score = correct_count / len(questions) if questions else 0.0
        attempt.answers = answers
        attempt.results = results
        attempt.score = score
        session.commit()

        return {
            "score": score,
            "results": results,
            "added_card_ids": added_card_ids,
            "due_now_count": due_now_count,
        }
    finally:
        session.close()


def list_tests(
    course_id: str, learner_id: str = learner_context.LEGACY_LOCAL_LEARNER_ID
) -> list[dict[str, Any]]:
    """Test-grouped: one entry per generated deck, each with its own
    ordered attempt history (ADR-022) — a course that's been retaken
    several times shows one card with N attempts, not N flat rows.
    """
    session = get_session()
    try:
        course_profile_id = (
            session.query(CourseLearningProfile.id)
            .filter_by(learner_id=learner_id, course_id=course_id)
            .scalar()
        )
        tests = (
            session.query(Test)
            .filter(Test.course_id == course_id)
            .order_by(Test.created_at.desc())
            .all()
        )
        result = []
        for t in tests:
            attempts = (
                session.query(TestAttempt)
                .filter(
                    TestAttempt.test_id == t.id,
                    TestAttempt.course_learning_profile_id == course_profile_id,
                )
                .order_by(TestAttempt.created_at.desc())
                .all()
            )
            result.append(
                {
                    "id": t.id,
                    "course_id": t.course_id,
                    "chapter_label": t.chapter_label,
                    "question_count": len(t.questions),
                    "created_at": t.created_at,
                    "attempts": [
                        {"id": a.id, "score": a.score, "created_at": a.created_at} for a in attempts
                    ],
                }
            )
        return result
    finally:
        session.close()
