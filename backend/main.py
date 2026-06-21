import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from SourceMind.backend.services.lesson_engine import LessonEngine
from SourceMind.backend.services.md_store import (
    Competency,
    Lesson,
    LessonState,
    MarkdownSubjectStore,
    Misconception,
    Quote,
    RetrievalCheck,
    SubjectDocument,
    TransferTask,
    WorkedExample,
)
from SourceMind.backend.services.llm_local import GroundingScore, LocalLLMResponse, LocalLLMService
from SourceMind.backend.services.srs_engine import EvaluationResult, SRSEngine, StudySession
from SourceMind.backend.routers.courses import router as courses_router
from SourceMind.backend.routers.upload import router as upload_router


def _cors_origins() -> list[str]:
    defaults = ["http://localhost:3000", "http://127.0.0.1:3000"]
    configured = [
        origin.strip()
        for origin in os.getenv("SOURCEMIND_CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    return [*defaults, *[origin for origin in configured if origin not in defaults]]


app = FastAPI(title="SourceMind API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(courses_router)
app.include_router(upload_router)

store = MarkdownSubjectStore()
srs_engine = SRSEngine()
llm_service = LocalLLMService()
lesson_engine = LessonEngine()


class StudySessionRequest(BaseModel):
    subject_id: str
    limit: int = Field(default=10, ge=1, le=50)


class StudyEvaluateRequest(BaseModel):
    subject_id: str
    competency_id: str
    correct: bool
    confidence: int = Field(ge=1, le=6)
    level: int | None = None
    response_text: str | None = None
    grounding: GroundingScore | None = None


class ExplainRequest(BaseModel):
    subject_id: str
    competency_id: str
    question: str


class LessonQuestionRequest(BaseModel):
    subject_id: str
    lesson_id: str
    question: str


class LessonQuestionResponse(BaseModel):
    response: str
    support_status: str
    quote_scope: str
    grounding: GroundingScore
    model: str


class RetrievalCheckEvaluateRequest(BaseModel):
    subject_id: str
    lesson_id: str
    check_id: str
    correct: bool
    confidence: int = Field(ge=1, le=6)
    answer: str | None = None


class RetrievalCheckEvaluateResponse(BaseModel):
    evaluation: EvaluationResult
    retrieval_check: RetrievalCheck


class LessonOverview(BaseModel):
    id: str
    title: str
    competency_id: str
    objective: str
    level: int
    mastery_percent: float


class LessonListResponse(BaseModel):
    subject_id: str
    lessons: list[LessonOverview]


class LessonDetailResponse(BaseModel):
    subject_id: str
    lesson: Lesson
    competency: Competency
    quotes: list[Quote]
    worked_examples: list[WorkedExample]
    retrieval_checks: list[RetrievalCheck]
    misconceptions: list[Misconception]
    transfer_tasks: list[TransferTask]
    state: LessonState
    interleaving_unlocked: bool


class TroubleArea(BaseModel):
    competency_id: str
    competency_name: str
    level: int
    last_score: float | None = None
    last_confidence: int


class SubjectSummary(BaseModel):
    subject_id: str
    current_level: int
    total_mastery: float
    progress_by_level: dict[str, float]
    tasks_due: int
    trouble_areas: list[TroubleArea]


class DashboardResponse(BaseModel):
    subjects: list[SubjectSummary]


class SubjectDetail(BaseModel):
    subject: SubjectDocument
    session: StudySession


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/subjects")
def list_subjects() -> dict[str, list[str]]:
    return {"subjects": store.list_subject_ids()}


@app.get("/dashboard")
def dashboard() -> DashboardResponse:
    summaries = []
    for subject_id in store.list_subject_ids():
        document = _load_subject(subject_id)
        session = srs_engine.build_session(document)
        summaries.append(_subject_summary(document, len(session.items)))
    return DashboardResponse(subjects=summaries)


@app.get("/subjects/{subject_id}")
def subject_detail(subject_id: str) -> SubjectDetail:
    try:
        document = _load_subject(subject_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return SubjectDetail(subject=document, session=srs_engine.build_session(document))


@app.post("/study/session")
def create_study_session(request: StudySessionRequest) -> StudySession:
    try:
        document = _load_subject(request.subject_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return srs_engine.build_session(document, limit=request.limit)


@app.post("/study/evaluate")
def evaluate_study_item(request: StudyEvaluateRequest) -> EvaluationResult:
    try:
        document = _load_subject(request.subject_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    grounding = request.grounding
    if grounding is None and request.response_text:
        related_quotes = [quote for quote in document.quotes if quote.competency_id == request.competency_id]
        grounding = llm_service.grounding_for_response(request.response_text, related_quotes)

    try:
        result = srs_engine.evaluate(
            document=document,
            competency_id=request.competency_id,
            correct=request.correct,
            confidence=request.confidence,
            grounding=grounding,
            level=request.level,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    store.save(document)
    return result


@app.post("/study/explain")
def explain_study_item(request: ExplainRequest) -> LocalLLMResponse:
    try:
        document = _load_subject(request.subject_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    competency = _competency(document, request.competency_id)
    direct_quotes = _related_quotes(document, competency)
    related_quotes = direct_quotes or _subject_quote_fallback(document)
    mastery_context = {
        "subject_id": document.subject_id,
        "competency_id": competency.id,
        "competency_name": competency.name,
        "level": competency.level,
        "mastery_percent": competency.mastery_percent,
        "dependencies": competency.dependencies,
        "quote_scope": "competency_or_prerequisite" if direct_quotes else "subject_fallback",
    }
    return llm_service.explain_with_critic(request.question, related_quotes, mastery_context)


@app.get("/lessons/{subject_id}", response_model=LessonListResponse)
def list_lessons(subject_id: str) -> LessonListResponse:
    try:
        document = _load_subject(subject_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    competencies = {item.id: item for item in document.competencies}
    return LessonListResponse(
        subject_id=document.subject_id,
        lessons=[
            LessonOverview(
                id=lesson.id,
                title=lesson.title,
                competency_id=lesson.competency_id,
                objective=lesson.objective,
                level=competencies[lesson.competency_id].level,
                mastery_percent=competencies[lesson.competency_id].mastery_percent,
            )
            for lesson in document.lesson_model
            if lesson.competency_id in competencies
        ],
    )


@app.get("/lessons/{subject_id}/{lesson_id}", response_model=LessonDetailResponse)
def lesson_detail(subject_id: str, lesson_id: str) -> LessonDetailResponse:
    try:
        document = _load_subject(subject_id)
        detail = lesson_engine.lesson_detail(document, lesson_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return LessonDetailResponse(subject_id=document.subject_id, **detail)


@app.post("/lessons/question", response_model=LessonQuestionResponse)
def ask_lesson_question(request: LessonQuestionRequest) -> LessonQuestionResponse:
    try:
        document = _load_subject(request.subject_id)
        quotes = lesson_engine.related_quotes_for_lesson(document, request.lesson_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    quote_scope = "lesson_related" if quotes else "subject_fallback"
    response = llm_service.explain_with_critic(
        question=request.question,
        quotes=quotes or _subject_quote_fallback(document),
        mastery_context={
            "subject_id": document.subject_id,
            "lesson_id": request.lesson_id,
            "quote_scope": quote_scope,
        },
    )
    support_status = _support_status(response.grounding, quote_scope=quote_scope)
    state = document.lesson_state.setdefault(request.lesson_id, LessonState())
    state.question_history.append({"question": request.question, "support_status": support_status})
    state.question_history = state.question_history[-20:]
    store.save(document)

    return LessonQuestionResponse(
        response=response.response,
        support_status=support_status,
        quote_scope=quote_scope,
        grounding=response.grounding,
        model=response.model,
    )


@app.post("/lessons/evaluate-check", response_model=RetrievalCheckEvaluateResponse)
def evaluate_retrieval_check(request: RetrievalCheckEvaluateRequest) -> RetrievalCheckEvaluateResponse:
    try:
        document = _load_subject(request.subject_id)
        lesson = next(item for item in document.lesson_model if item.id == request.lesson_id)
        check = next(item for item in document.retrieval_checks if item.id == request.check_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StopIteration as exc:
        raise HTTPException(status_code=404, detail="Unknown lesson_id or check_id") from exc

    if request.check_id not in lesson.retrieval_check_ids:
        raise HTTPException(
            status_code=422,
            detail=f"Check {request.check_id} does not belong to lesson {request.lesson_id}",
        )

    grounding = None
    if request.answer:
        related_quotes = [quote for quote in document.quotes if quote.competency_id == check.competency_id]
        grounding = llm_service.grounding_for_response(request.answer, related_quotes)

    try:
        evaluation = srs_engine.evaluate(
            document=document,
            competency_id=check.competency_id,
            correct=request.correct,
            confidence=request.confidence,
            grounding=grounding,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    updated_check = lesson_engine.update_retrieval_check(
        document=document,
        lesson_id=request.lesson_id,
        check_id=request.check_id,
        correct=request.correct,
        confidence=request.confidence,
        mastery_percent=evaluation.mastery_percent,
        interval=evaluation.interval,
    )
    store.save(document)
    return RetrievalCheckEvaluateResponse(evaluation=evaluation, retrieval_check=updated_check)


@app.get("/lessons/{subject_id}/reviews/next")
def next_lesson_review(subject_id: str) -> dict[str, object]:
    try:
        document = _load_subject(subject_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    checks = sorted(document.retrieval_checks, key=lambda item: (item.interval, item.mastery_percent))
    return {"subject_id": document.subject_id, "retrieval_check": checks[0] if checks else None}


def _load_subject(subject_id: str) -> SubjectDocument:
    document = store.load(subject_id)
    if document.lesson_model:
        before_repair = document.model_dump(mode="json")
        lesson_engine.ensure_lesson_model(document)
        if document.model_dump(mode="json") != before_repair:
            store.save(document)
    return document


def _support_status(grounding: GroundingScore, quote_scope: str = "lesson_related") -> str:
    if grounding.grounded_pct >= 50:
        if quote_scope != "lesson_related":
            return "inferred"
        return "grounded"
    if grounding.grounded_pct + grounding.inference_pct >= 60 and grounding.prediction_pct <= 40:
        return "inferred"
    return "outside_scope"


def _subject_summary(document: SubjectDocument, tasks_due: int) -> SubjectSummary:
    trouble_areas = []
    by_id = {competency.id: competency for competency in document.competencies}
    for competency_id, srs in document.srs_data.items():
        if srs.last_score is None or not srs.confidence_history:
            continue
        last_confidence = srs.confidence_history[-1]
        if srs.last_score < 60 and last_confidence >= 5 and competency_id in by_id:
            competency = by_id[competency_id]
            trouble_areas.append(
                TroubleArea(
                    competency_id=competency.id,
                    competency_name=competency.name,
                    level=competency.level,
                    last_score=srs.last_score,
                    last_confidence=last_confidence,
                )
            )

    progress = document.frontmatter.understanding_percentages or _progress_by_level(document.competencies)
    return SubjectSummary(
        subject_id=document.subject_id,
        current_level=document.frontmatter.current_level,
        total_mastery=document.frontmatter.total_mastery,
        progress_by_level=progress,
        tasks_due=tasks_due,
        trouble_areas=trouble_areas,
    )


def _progress_by_level(competencies: list[Competency]) -> dict[str, float]:
    progress = {}
    for level in (1, 2, 3):
        level_items = [item for item in competencies if item.level == level]
        progress[f"level_{level}"] = (
            round(sum(item.mastery_percent for item in level_items) / len(level_items), 2) if level_items else 0
        )
    return progress


def _competency(document: SubjectDocument, competency_id: str) -> Competency:
    for competency in document.competencies:
        if competency.id == competency_id:
            return competency
    raise HTTPException(status_code=404, detail=f"Unknown competency_id: {competency_id}")


def _related_quotes(document: SubjectDocument, competency: Competency) -> list[Quote]:
    ids = {competency.id, *competency.dependencies}
    return [quote for quote in document.quotes if quote.competency_id in ids]


def _subject_quote_fallback(document: SubjectDocument, limit: int = 8) -> list[Quote]:
    return document.quotes[:limit]
