from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from pypdf import PdfReader

try:
    import ollama
except ImportError:  # pragma: no cover
    ollama = None

from SourceMind.backend.services.course_models import (
    Chapter,
    CheckItem,
    Concept,
    ConceptMastery,
    CourseCompetency,
    CourseDocument,
    CourseStatus,
    LessonBlock,
    QuizItem,
    SectionLesson,
    SourceFile,
    SourceSpan,
    SupportStatus,
    WorkedExample,
)


MAX_OUTLINE_SECTIONS = 120
MIN_LESSON_BLOCK_WORDS = 180
REQUIRED_LESSON_BLOCK_KINDS = {"teaching", "definition", "worked_example", "common_mistake", "self_explanation"}
MASTERY_GATE_PERCENT = 80


class CourseGenerationError(RuntimeError):
    pass


class LLMUnavailableError(CourseGenerationError):
    pass


@dataclass(frozen=True)
class ExtractedPage:
    source_file_id: str
    source_name: str
    page_number: int
    text: str


class CourseEngine:
    """Build ordered textbook courses from source PDFs."""

    def __init__(self, model: str = "llama3.1", allow_deterministic_fallback: bool = False) -> None:
        self.model = model
        self.allow_deterministic_fallback = allow_deterministic_fallback

    def create_draft_from_pdfs(self, course_id: str, title: str, pdf_paths: list[Path]) -> CourseDocument:
        source_files = [
            SourceFile(id=f"SRC_{index + 1}", filename=path.name, order=index)
            for index, path in enumerate(pdf_paths)
        ]
        pages = self.extract_pages(pdf_paths, source_files)
        if not pages:
            raise CourseGenerationError("No selectable source text could be extracted from the uploaded PDFs.")

        chapters = self.detect_outline(title, source_files, pages)
        competencies = self.build_competency_map(chapters)
        return CourseDocument(
            course_id=course_id,
            title=title,
            status=CourseStatus.outline_draft,
            source_files=source_files,
            competencies=competencies,
            chapters=chapters,
            notes="Draft mastery course generated from ordered source materials. Review the outline, then generate the course book.",
        )

    def extract_pages(self, pdf_paths: list[Path], source_files: list[SourceFile]) -> list[ExtractedPage]:
        pages: list[ExtractedPage] = []
        for path, source_file in zip(pdf_paths, source_files, strict=True):
            try:
                reader = PdfReader(str(path))
            except Exception as exc:
                raise CourseGenerationError(
                    f"Could not read PDF text from {path.name}. Confirm the file is a valid, text-selectable PDF."
                ) from exc
            for index, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                cleaned = re.sub(r"[ \t]+", " ", text).strip()
                if cleaned:
                    pages.append(
                        ExtractedPage(
                            source_file_id=source_file.id,
                            source_name=source_file.filename,
                            page_number=index,
                            text=cleaned,
                        )
                    )
        return pages

    def detect_outline(
        self,
        title: str,
        source_files: list[SourceFile],
        pages: list[ExtractedPage],
    ) -> list[Chapter]:
        heading_sections = self._sections_from_table_of_contents(pages)
        if not heading_sections:
            heading_sections = self._sections_from_headings(pages)
        if not heading_sections:
            heading_sections = self._sections_from_page_chunks(title, pages)

        chapters_by_number: dict[str, Chapter] = {}
        for order, section in enumerate(heading_sections):
            chapter_number = section["chapter_number"]
            chapter = chapters_by_number.get(chapter_number)
            if chapter is None:
                chapter = Chapter(
                    id=f"CH_{len(chapters_by_number) + 1}",
                    number=chapter_number,
                    title=section["chapter_title"],
                    order=len(chapters_by_number),
                    sections=[],
                )
                chapters_by_number[chapter_number] = chapter
            section_id = f"SEC_{order + 1}"
            chapter.sections.append(
                SectionLesson(
                    id=section_id,
                    chapter_id=chapter.id,
                    number=section["section_number"],
                    title=section["title"],
                    order=order,
                    source_spans=section["source_spans"],
                    competency_ids=[f"COMP_{order + 1}"],
                    lesson_goal=self._lesson_goal(section["title"]),
                    status=CourseStatus.outline_draft,
                )
            )

        return list(chapters_by_number.values())

    def build_competency_map(self, chapters: list[Chapter]) -> list[CourseCompetency]:
        competencies: list[CourseCompetency] = []
        prior_by_chapter: dict[str, str] = {}
        previous_id: str | None = None
        for index, section in enumerate((section for chapter in chapters for section in chapter.sections), start=1):
            competency_id = f"COMP_{index}"
            chapter_number = section.number.split(".", 1)[0]
            prereqs = []
            if previous_id:
                prereqs.append(previous_id)
            chapter_anchor = prior_by_chapter.get(chapter_number)
            if chapter_anchor and chapter_anchor not in prereqs:
                prereqs.append(chapter_anchor)
            competency = CourseCompetency(
                id=competency_id,
                title=self._competency_title(section.title),
                description=(
                    f"Use {section.title} accurately, explain the idea in your own words, "
                    "and apply it to a new problem without copying the source."
                ),
                level=1 if index <= 4 else 2 if index <= 12 else 3,
                prerequisite_ids=prereqs[-2:],
                lesson_ids=[section.id],
            )
            section.competency_ids = [competency_id]
            section.lesson_goal = self._lesson_goal(section.title)
            competencies.append(competency)
            prior_by_chapter.setdefault(chapter_number, competency_id)
            previous_id = competency_id
        return competencies

    def generate_lessons(
        self,
        course: CourseDocument,
        progress_callback: Callable[[CourseDocument, SectionLesson], None] | None = None,
    ) -> CourseDocument:
        if not course.competencies:
            course.competencies = self.build_competency_map(course.chapters)
        prior_section_concept_ids: list[str] = []
        for chapter in course.chapters:
            for section in chapter.sections:
                if section.status == CourseStatus.ready and section.concepts:
                    prior_section_concept_ids.extend(concept.id for concept in section.concepts)
                    continue
                self._generate_section(section, prior_section_concept_ids, course.competencies)
                prior_section_concept_ids.extend(concept.id for concept in section.concepts)
                if progress_callback:
                    progress_callback(course, section)
        self._sync_competency_mastery(course)
        course.status = CourseStatus.ready if all(section.status == CourseStatus.ready for section in course.all_sections()) else CourseStatus.needs_review
        return course

    def chat(
        self,
        course: CourseDocument,
        section_id: str,
        question: str,
        history: list[Any] | None = None,
    ) -> tuple[str, SupportStatus, list[str]]:
        section = self.section_by_id(course, section_id)
        evidence = self._section_evidence(section)
        recent_history = self._format_chat_history(history or [])
        system = (
            "You are SourceMind's right-side tutor. Help the student understand the current workbook lesson. "
            "Use the course PDF evidence first. If you use general tutoring knowledge, explicitly label it as outside-course knowledge. "
            "Keep replies conversational, concise, and useful for a student actively working through the lesson."
        )
        prompt = (
            f"Course: {course.title}\n"
            f"Section: {section.number} {section.title}\n"
            f"Recent tutor conversation:\n{recent_history or 'No previous turns.'}\n\n"
            f"Question: {question}\n\n"
            f"PDF evidence:\n{evidence[:6000]}"
        )
        answer = self._chat(system, prompt)
        refs = [span_ref(span) for span in section.source_spans[:3]]
        if not answer:
            if not self.allow_deterministic_fallback:
                return (
                    "Local Ollama tutor is unavailable, so SourceMind is not generating a detailed answer. "
                    f"Start Ollama with the configured model ({self.model}) and ask again, or review the cited course evidence in this lesson.",
                    SupportStatus.outside_knowledge,
                    [],
                )
            answer = self._fallback_chat_answer(question, evidence)
        support = self.support_status(answer, evidence)
        return answer, support, refs

    def _format_chat_history(self, history: list[Any]) -> str:
        turns = []
        for turn in history[-6:]:
            question = getattr(turn, "question", "")
            answer = getattr(turn, "answer", "")
            if question:
                turns.append(f"Student: {question[:500]}")
            if answer:
                turns.append(f"Tutor: {answer[:700]}")
        return "\n".join(turns)

    def grade_answer(self, expected: str, answer: str, confidence: int) -> tuple[float, str]:
        expected_terms = self._terms(expected)
        answer_terms = self._terms(answer)
        if not answer_terms:
            return 0, "No answer was provided."
        overlap = expected_terms & answer_terms
        score = round(min(100, len(overlap) * 100 / max(1, len(expected_terms))))
        if confidence <= 2 and score >= 70:
            score = max(60, score - 10)
        if score >= 70:
            return score, "The answer preserves the expected meaning."
        return score, "Review the lesson evidence and try to include the core idea in your own words."

    def record_mastery_review(self, mastery: ConceptMastery, score: float, confidence: int) -> None:
        now = datetime.now(UTC)
        mastery.last_score = score
        mastery.confidence_history.append(confidence)
        mastery.failure_streak = 0 if score >= 70 else mastery.failure_streak + 1

        if score < 70 and confidence >= 5:
            interval_days = 0
        elif score < 70:
            interval_days = 1
        elif score >= 90 and confidence >= 5:
            interval_days = 7
        elif score >= MASTERY_GATE_PERCENT:
            interval_days = 3
        else:
            interval_days = 1

        mastery.review_interval = interval_days
        mastery.last_reviewed_at = now.isoformat(timespec="seconds")
        mastery.next_review_at = (now + timedelta(days=interval_days)).isoformat(timespec="seconds")

    def due_review_items(self, course: CourseDocument, include_upcoming: bool = False) -> list[dict[str, Any]]:
        now = datetime.now(UTC)
        self._sync_competency_mastery(course)
        items: list[dict[str, Any]] = []
        sections_by_id = {section.id: section for section in course.all_sections()}

        for competency in course.competencies:
            section = next(
                (
                    sections_by_id[lesson_id]
                    for lesson_id in competency.lesson_ids
                    if lesson_id in sections_by_id and sections_by_id[lesson_id].status == CourseStatus.ready
                ),
                None,
            )
            if section is None:
                continue

            due_at = self._parse_iso_datetime(competency.mastery.next_review_at)
            attempted = competency.mastery.last_score is not None or bool(competency.mastery.confidence_history)
            if not attempted:
                continue
            due = bool(due_at and due_at <= now)
            low_after_attempt = attempted and competency.mastery.mastery_percent < MASTERY_GATE_PERCENT
            if not due and not low_after_attempt and not include_upcoming:
                continue

            if due and competency.mastery.last_score is not None and competency.mastery.last_score < 70:
                reason = "Needs immediate review after a missed check."
            elif due:
                reason = "Scheduled spaced review is due."
            elif low_after_attempt:
                reason = "Mastery is below the 80% gate after recent practice."
            else:
                reason = "Upcoming spaced review."

            items.append(
                {
                    "course_id": course.course_id,
                    "course_title": course.title,
                    "competency_id": competency.id,
                    "competency_title": competency.title,
                    "section_id": section.id,
                    "section_number": section.number,
                    "section_title": section.title,
                    "mastery_percent": competency.mastery.mastery_percent,
                    "last_score": competency.mastery.last_score,
                    "next_review_at": competency.mastery.next_review_at,
                    "due": due or low_after_attempt,
                    "reason": reason,
                }
            )

        return sorted(
            items,
            key=lambda item: (
                0 if item["due"] else 1,
                item["next_review_at"] or "9999",
                item["mastery_percent"],
            ),
        )

    def section_by_id(self, course: CourseDocument, section_id: str) -> SectionLesson:
        for section in course.all_sections():
            if section.id == section_id:
                return section
        raise KeyError(f"Unknown section_id: {section_id}")

    def check_by_id(self, section: SectionLesson, check_id: str) -> CheckItem:
        for check in section.checks:
            if check.id == check_id:
                return check
        raise KeyError(f"Unknown check_id: {check_id}")

    def submit_quiz(self, section: SectionLesson, answers: dict[str, str], confidence: int) -> dict[str, Any]:
        item_results = []
        scores = []
        for item in section.mastery_quiz:
            score, feedback = self.grade_answer(item.expected_answer, answers.get(item.id, ""), confidence)
            scores.append(score)
            item_results.append({"item_id": item.id, "score": score, "feedback": feedback})

        average = round(sum(scores) / len(scores), 2) if scores else 0
        for concept in section.concepts:
            old = concept.mastery.mastery_percent
            concept.mastery.mastery_percent = round(max(old, min(100, average)), 2)
            self.record_mastery_review(concept.mastery, average, confidence)
        section.completed = average >= 70 and all(check.completed for check in section.checks[:2])
        return {"score": average, "passed": section.completed, "items": item_results}

    def _generate_section(
        self,
        section: SectionLesson,
        prerequisite_ids: list[str],
        course_competencies: list[CourseCompetency] | None = None,
    ) -> None:
        evidence = self._section_evidence(section)
        lesson_text = self._clean_lesson_source_text(section, evidence)
        if len(self._terms(lesson_text)) < 6:
            self._clear_generated_section(section)
            section.status = CourseStatus.needs_review
            return

        competencies = [competency for competency in (course_competencies or []) if competency.id in section.competency_ids]
        payload = self._generate_with_ollama(section, evidence, competencies)
        if payload is None:
            if not self.allow_deterministic_fallback:
                section.status = CourseStatus.needs_review
                raise LLMUnavailableError(
                    f"Local Ollama model is unavailable, so SourceMind cannot generate workbook lessons for {section.number} {section.title}. "
                    f"Start Ollama with the configured model ({self.model}) and try again."
                )
            payload = self._source_bound_section_payload(section, evidence, competencies)

        section.learning_objectives = payload["learning_objectives"]
        section.concepts = [
            Concept(
                id=f"{section.id}_C{index + 1}",
                title=item["title"],
                explanation=item["explanation"],
                source_refs=[span_ref(span) for span in section.source_spans[:2]],
                prerequisites=prerequisite_ids[-2:],
            )
            for index, item in enumerate(payload["concepts"])
        ]
        concept_ids = [concept.id for concept in section.concepts]
        refs = [span_ref(span) for span in section.source_spans[:2]]
        section.lesson_blocks = [
            LessonBlock(
                id=f"{section.id}_B{index + 1}",
                kind=item["kind"],
                title=item["title"],
                body=item["body"],
                source_refs=refs,
            )
            for index, item in enumerate(payload["lesson_blocks"])
        ]
        section.worked_examples = [
            WorkedExample(
                id=f"{section.id}_WE1",
                title=payload["worked_example"]["title"],
                prompt=payload["worked_example"]["prompt"],
                steps=payload["worked_example"]["steps"],
                source_refs=refs,
            )
        ]
        section.checks = [
            CheckItem(
                id=f"{section.id}_CHK{index + 1}",
                kind=item["kind"],
                prompt=item["prompt"],
                expected_answer=item["expected_answer"],
                choices=item.get("choices", []),
                source_refs=refs,
                concept_ids=concept_ids,
            )
            for index, item in enumerate(payload["checks"])
        ]
        section.mastery_quiz = [
            QuizItem(
                id=f"{section.id}_Q{index + 1}",
                kind=item["kind"],
                prompt=item["prompt"],
                expected_answer=item["expected_answer"],
                source_refs=refs,
                concept_ids=concept_ids,
            )
            for index, item in enumerate(payload["mastery_quiz"])
        ]
        section.prerequisites = prerequisite_ids[-2:]
        section.status = CourseStatus.ready

    def _clear_generated_section(self, section: SectionLesson) -> None:
        section.learning_objectives = []
        section.concepts = []
        section.lesson_blocks = []
        section.worked_examples = []
        section.checks = []
        section.mastery_quiz = []
        section.prerequisites = []

    def _generate_with_ollama(
        self,
        section: SectionLesson,
        evidence: str,
        competencies: list[CourseCompetency] | None = None,
    ) -> dict[str, Any] | None:
        if ollama is None:
            return None
        competency_context = "\n".join(
            f"- {competency.id}: {competency.title}; goal: {competency.description}; prerequisites: {', '.join(competency.prerequisite_ids) or 'none'}"
            for competency in competencies or []
        )
        prompt = f"""
Create a SourceMind course-book lesson for this textbook section.
Base the lesson on the PDF evidence, but teach the concept in your own words as a coherent class lesson.
Do not paste long source excerpts into the lesson. Use source text as grounding, not as the lesson itself.
The lesson must teach toward the listed competencies and prepare the student for later transfer.
Return strict JSON with:
learning_objectives: string[]
concepts: [{{title, explanation}}]
lesson_blocks: [{{kind, title, body}}] where kind is teaching, definition, worked_example, common_mistake, self_explanation.
Each lesson block body must be a real paragraph of 90-180 words, not a one-sentence summary.
worked_example: {{title, prompt, steps}}
checks: [{{kind, prompt, expected_answer, choices}}] where kind is short_answer, multiple_choice, self_explanation
mastery_quiz: [{{kind, prompt, expected_answer}}] where kind is recall, application, explanation

Section: {section.number} {section.title}
Lesson goal: {section.lesson_goal}
Competencies:
{competency_context or "Derive one practical competency from the section title and source."}
PDF evidence:
{evidence[:9000]}
""".strip()
        try:
            result = ollama.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You write source-grounded workbook lessons. Return only JSON."},
                    {"role": "user", "content": prompt},
                ],
                format="json",
            )
            payload = json.loads(result.get("message", {}).get("content", "{}"))
            return self._normalize_payload(payload, section, evidence, competencies)
        except Exception:
            return None

    def _normalize_payload(
        self,
        payload: dict[str, Any],
        section: SectionLesson,
        evidence: str,
        competencies: list[CourseCompetency] | None = None,
    ) -> dict[str, Any]:
        fallback = self._source_bound_section_payload(section, evidence, competencies)
        if not isinstance(payload, dict):
            return fallback

        learning_objectives = [
            self._coerce_text(item, "")
            for item in self._coerce_list(payload.get("learning_objectives"))
        ]
        learning_objectives = [item for item in learning_objectives if item][:4] or fallback["learning_objectives"]

        concepts = []
        for item in self._coerce_list(payload.get("concepts"))[:4]:
            if not isinstance(item, dict):
                continue
            title = self._coerce_text(item.get("title"), "")
            explanation = self._coerce_text(item.get("explanation"), "")
            if title and explanation:
                concepts.append({"title": title, "explanation": explanation})
        if not concepts:
            concepts = fallback["concepts"]

        block_kinds = {"teaching", "source_excerpt", "definition", "worked_example", "common_mistake", "quick_check", "self_explanation"}
        lesson_blocks = []
        for item in self._coerce_list(payload.get("lesson_blocks"))[:8]:
            if not isinstance(item, dict):
                continue
            kind = self._coerce_choice(item.get("kind"), block_kinds, "teaching")
            title = self._coerce_text(item.get("title"), "")
            body = self._coerce_text(item.get("body"), "")
            if title and body:
                lesson_blocks.append({"kind": kind, "title": title, "body": body})
        if not self._lesson_blocks_are_substantial(lesson_blocks):
            lesson_blocks = fallback["lesson_blocks"]

        worked_example = payload.get("worked_example") if isinstance(payload.get("worked_example"), dict) else {}
        worked_steps = [
            self._coerce_text(item, "")
            for item in self._coerce_list(worked_example.get("steps") if isinstance(worked_example, dict) else None)
        ]
        worked_steps = [item for item in worked_steps if item][:6]
        normalized_worked_example = {
            "title": self._coerce_text(worked_example.get("title") if isinstance(worked_example, dict) else None, fallback["worked_example"]["title"]),
            "prompt": self._coerce_text(worked_example.get("prompt") if isinstance(worked_example, dict) else None, fallback["worked_example"]["prompt"]),
            "steps": worked_steps or fallback["worked_example"]["steps"],
        }

        check_kinds = {"short_answer", "multiple_choice", "self_explanation"}
        checks = []
        for item in self._coerce_list(payload.get("checks"))[:5]:
            if not isinstance(item, dict):
                continue
            prompt = self._coerce_text(item.get("prompt"), "")
            expected_answer = self._coerce_text(item.get("expected_answer"), "")
            if not prompt or not expected_answer:
                continue
            choices = [self._coerce_text(choice, "") for choice in self._coerce_list(item.get("choices"))]
            checks.append(
                {
                    "kind": self._coerce_choice(item.get("kind"), check_kinds, "short_answer"),
                    "prompt": prompt,
                    "expected_answer": expected_answer,
                    "choices": [choice for choice in choices if choice][:4],
                }
            )
        if len(checks) < 3:
            checks = fallback["checks"]

        quiz_kinds = {"recall", "application", "explanation"}
        mastery_quiz = []
        for item in self._coerce_list(payload.get("mastery_quiz"))[:5]:
            if not isinstance(item, dict):
                continue
            prompt = self._coerce_text(item.get("prompt"), "")
            expected_answer = self._coerce_text(item.get("expected_answer"), "")
            if prompt and expected_answer:
                mastery_quiz.append(
                    {
                        "kind": self._coerce_choice(item.get("kind"), quiz_kinds, "recall"),
                        "prompt": prompt,
                        "expected_answer": expected_answer,
                    }
                )
        if len(mastery_quiz) < 3:
            mastery_quiz = fallback["mastery_quiz"]

        return {
            "learning_objectives": learning_objectives,
            "concepts": concepts,
            "lesson_blocks": lesson_blocks,
            "worked_example": normalized_worked_example,
            "checks": checks,
            "mastery_quiz": mastery_quiz,
        }

    def repair_thin_lessons(self, course: CourseDocument) -> bool:
        changed = False
        competencies_by_id = {competency.id: competency for competency in course.competencies}
        for section in course.all_sections():
            if section.status != CourseStatus.ready:
                continue
            lesson_blocks = [block.model_dump(mode="json") for block in section.lesson_blocks]
            if self._lesson_blocks_are_substantial(lesson_blocks):
                continue
            competencies = [competencies_by_id[competency_id] for competency_id in section.competency_ids if competency_id in competencies_by_id]
            fallback = self._source_bound_section_payload(section, self._section_evidence(section), competencies)
            refs = [span_ref(span) for span in section.source_spans[:2]]
            section.lesson_blocks = [
                LessonBlock(
                    id=f"{section.id}_B{index + 1}",
                    kind=item["kind"],
                    title=item["title"],
                    body=item["body"],
                    source_refs=refs,
                )
                for index, item in enumerate(fallback["lesson_blocks"])
            ]
            if not section.worked_examples:
                section.worked_examples = [
                    WorkedExample(
                        id=f"{section.id}_WE1",
                        title=fallback["worked_example"]["title"],
                        prompt=fallback["worked_example"]["prompt"],
                        steps=fallback["worked_example"]["steps"],
                        source_refs=refs,
                    )
                ]
            changed = True
        return changed

    def _lesson_blocks_are_substantial(self, lesson_blocks: list[dict[str, Any]]) -> bool:
        if len(lesson_blocks) < len(REQUIRED_LESSON_BLOCK_KINDS):
            return False
        kinds = {self._coerce_text(block.get("kind"), "") for block in lesson_blocks if isinstance(block, dict)}
        if not REQUIRED_LESSON_BLOCK_KINDS.issubset(kinds):
            return False
        total_words = sum(len(re.findall(r"\b\w+\b", self._coerce_text(block.get("body"), ""))) for block in lesson_blocks if isinstance(block, dict))
        return total_words >= MIN_LESSON_BLOCK_WORDS

    def _coerce_text(self, value: Any, fallback: str) -> str:
        if isinstance(value, str):
            cleaned = re.sub(r"\s+", " ", value).strip()
            return cleaned[:4000] if cleaned else fallback
        return fallback

    def _coerce_list(self, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

    def _coerce_choice(self, value: Any, allowed: set[str], fallback: str) -> str:
        return value if isinstance(value, str) and value in allowed else fallback

    def _source_bound_section_payload(
        self,
        section: SectionLesson,
        evidence: str,
        competencies: list[CourseCompetency] | None = None,
    ) -> dict[str, Any]:
        lesson_text = self._clean_lesson_source_text(section, evidence)
        sentences = self._sentences(lesson_text)
        primary = sentences[0] if sentences else evidence[:240]
        secondary = sentences[1] if len(sentences) > 1 else primary
        concept_title = competencies[0].title if competencies else self._concept_title(section.title, primary)
        competency_goal = competencies[0].description if competencies else section.lesson_goal or self._lesson_goal(section.title)
        return {
            "learning_objectives": [
                f"Explain the purpose of {concept_title} without reading from the source.",
                f"Use the basic procedure or idea behind {concept_title} in a simple case.",
                f"Connect {concept_title} to earlier course skills before moving to harder transfer.",
            ],
            "concepts": [
                {
                    "title": concept_title,
                    "explanation": (
                        f"{concept_title} is a course competency for this lesson. "
                        f"The learning target is: {competency_goal} Source grounding: {primary}"
                    ),
                }
            ],
            "lesson_blocks": [
                {
                    "kind": "teaching",
                    "title": f"Big idea: {concept_title}",
                    "body": (
                        f"This lesson is about learning to use {concept_title}, not just recognizing words from the PDF. "
                        f"Start from the course goal: {competency_goal} In practice, that means you should be able to name the idea, "
                        "explain when it applies, and carry out a simple example without looking back at the source."
                    ),
                },
                {
                    "kind": "definition",
                    "title": "Core definition or rule",
                    "body": (
                        f"The source detail to anchor this lesson is: {secondary} "
                        f"Rewrite that in your own words as a definition, rule, or decision you can use while solving."
                    ),
                },
                {
                    "kind": "worked_example",
                    "title": "How to use it",
                    "body": (
                        "Work from idea to action: first identify the quantity, expression, or situation the lesson is about; "
                        "then choose the rule that fits; then check that the result still matches the meaning of the original problem."
                    ),
                },
                {
                    "kind": "common_mistake",
                    "title": "Common mistake",
                    "body": (
                        "A common failure is copying the surface procedure while missing the condition that made it legal. "
                        f"For {concept_title}, always say why the step is allowed before trusting the answer."
                    ),
                },
                {
                    "kind": "self_explanation",
                    "title": "Explain it back",
                    "body": (
                        f"Before moving on, explain {concept_title} in three sentences: what it is, when to use it, "
                        "and how it connects to the previous lesson."
                    ),
                },
            ],
            "worked_example": {
                "title": f"Worked example: {concept_title}",
                "prompt": f"Teach a simple use of {concept_title}.",
                "steps": [
                    f"Name the target competency: {concept_title}.",
                    f"State the source-grounded idea: {primary}",
                    "Set up a small example that uses only this idea and earlier prerequisites.",
                    "Carry out the step slowly and explain why each move is valid.",
                    "Check the answer against the meaning of the problem, not just the symbols.",
                ],
            },
            "checks": [
                {"kind": "short_answer", "prompt": f"What problem does {concept_title} help you solve?", "expected_answer": competency_goal, "choices": []},
                {"kind": "multiple_choice", "prompt": f"Which statement best describes the role of {concept_title}?", "expected_answer": competency_goal, "choices": [competency_goal, "It is only a page title and has no procedure.", "It is unrelated to the previous lesson."]},
                {"kind": "self_explanation", "prompt": f"Explain {concept_title} in your own words and include one condition for using it.", "expected_answer": secondary, "choices": []},
            ],
            "mastery_quiz": [
                {"kind": "recall", "prompt": f"State the core idea of {concept_title}.", "expected_answer": primary},
                {"kind": "application", "prompt": f"Describe how you would apply {concept_title} to a new simple example.", "expected_answer": secondary},
                {"kind": "explanation", "prompt": f"Explain how {concept_title} builds toward the course competency.", "expected_answer": competency_goal},
            ],
        }

    def _clean_lesson_source_text(self, section: SectionLesson, evidence: str) -> str:
        raw = "\n".join(span.text for span in section.source_spans if span.text) or evidence
        if self._is_low_value_text(raw):
            return ""
        cleaned_lines = []
        section_title = re.escape(section.title.strip())
        section_number = re.escape(section.number.strip())
        for line in raw.splitlines():
            line = re.sub(r"\s+", " ", line).strip()
            if not line:
                continue
            if re.match(r"^Chapter\s+[0-9A-Za-z.-]+", line, re.IGNORECASE):
                continue
            if re.match(rf"^{section_number}\s+{section_title}$", line, re.IGNORECASE):
                continue
            cleaned_lines.append(line)
        cleaned = " ".join(cleaned_lines) or re.sub(r"\[[^\]]+\]\s*", "", evidence)
        return "" if self._is_low_value_text(cleaned) else cleaned

    def _sections_from_table_of_contents(self, pages: list[ExtractedPage]) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        current_chapter_number: str | None = None
        current_chapter_title = "Course Foundations"
        for page in pages[:20]:
            if "contents" not in page.text.lower() and len(re.findall(r"\.{3,}\s*\d+", page.text)) < 4:
                continue
            logical_lines = self._toc_lines(page.text)
            for line in logical_lines:
                chapter_match = re.match(r"Chapter\s+([0-9A-Za-z.-]+)\s*:?\s*(.+?)(?:\.{3,}|\s{2,}|\s+\d+$|$)", line, re.IGNORECASE)
                if chapter_match:
                    current_chapter_number = chapter_match.group(1)
                    current_chapter_title = self._clean_title(chapter_match.group(2))
                    continue
                section_match = re.match(r"([0-9]+(?:\.[0-9]+))\s+(.+?)\.{2,}\s*\.?\s*([0-9]{1,4})\s*$", line)
                if not section_match:
                    section_match = re.match(r"([0-9]+(?:\.[0-9]+))\s+(.+?)[.\s]+([0-9]{1,4})\s*$", line)
                if not section_match:
                    section_match = re.match(r"([0-9]+(?:\.[0-9]+))\s+(.+?)\s+([0-9]{1,4})\s*$", line)
                if not section_match:
                    continue
                section_number = section_match.group(1)
                title = self._clean_title(section_match.group(2))
                if not self._is_plausible_section_heading(f"{section_number} {title}", section_number, title, current_chapter_number):
                    continue
                page_start = int(section_match.group(3))
                chapter_number = current_chapter_number or section_number.split(".", 1)[0]
                source_span = self._source_span_for_printed_page(pages, page.source_file_id, page_start)
                sections.append(
                    {
                        "chapter_number": chapter_number,
                        "chapter_title": current_chapter_title,
                        "section_number": section_number,
                        "title": title,
                        "source_spans": [source_span],
                    }
                )
        return self._dedupe_sections(sections) if len(sections) >= 4 else []

    def _toc_lines(self, text: str) -> list[str]:
        raw_lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
        lines: list[str] = []
        index = 0
        while index < len(raw_lines):
            line = raw_lines[index]
            if re.match(r"^\d+(?:\.\d+)\s+.+\.\.{2,}\s*$", line) and index + 1 < len(raw_lines) and re.match(r"^\d{1,4}$", raw_lines[index + 1]):
                line = f"{line}{raw_lines[index + 1]}"
                index += 1
            lines.append(line)
            index += 1
        return lines

    def _source_span_for_printed_page(
        self,
        pages: list[ExtractedPage],
        source_file_id: str,
        page_start: int,
    ) -> SourceSpan:
        same_source = [page for page in pages if page.source_file_id == source_file_id]
        candidates = [page for page in same_source if page.page_number >= page_start and not self._is_low_value_text(page.text)]
        selected = candidates[0] if candidates else next((page for page in same_source if not self._is_low_value_text(page.text)), same_source[0])
        nearby = [
            page.text
            for page in same_source
            if selected.page_number <= page.page_number <= selected.page_number + 1 and not self._is_low_value_text(page.text)
        ]
        text = "\n".join(nearby)[:5000] or selected.text[:5000]
        return SourceSpan(
            source_file_id=selected.source_file_id,
            source_name=selected.source_name,
            page_start=selected.page_number,
            page_end=selected.page_number,
            text=text,
        )

    def _sections_from_headings(self, pages: list[ExtractedPage]) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        current_chapter_number: str | None = None
        current_chapter_title = "Course Foundations"
        for page in pages:
            if self._is_low_value_text(page.text):
                continue
            lines = [line.strip() for line in page.text.splitlines() if line.strip()]
            for line in lines[:18]:
                chapter_match = re.match(r"Chapter\s+([0-9A-Za-z.-]+)\s*:?\s*(.{3,80})", line, re.IGNORECASE)
                if chapter_match:
                    current_chapter_number = chapter_match.group(1)
                    current_chapter_title = self._clean_title(chapter_match.group(2))
                section_match = re.match(r"([0-9]+(?:\.[0-9]+)+)\s+(.{3,90})", line)
                if section_match:
                    section_number = section_match.group(1)
                    title = self._clean_title(section_match.group(2))
                    if not self._is_plausible_section_heading(line, section_number, title, current_chapter_number):
                        continue
                    chapter_number = current_chapter_number or section_number.split(".", 1)[0]
                    sections.append(
                        {
                            "chapter_number": chapter_number,
                            "chapter_title": current_chapter_title,
                            "section_number": section_number,
                            "title": title,
                            "source_spans": [SourceSpan(source_file_id=page.source_file_id, source_name=page.source_name, page_start=page.page_number, page_end=page.page_number, text=page.text[:3500])],
                        }
                    )
        return self._dedupe_sections(sections)

    def _sections_from_page_chunks(self, title: str, pages: list[ExtractedPage]) -> list[dict[str, Any]]:
        sections = []
        for index, page in enumerate(pages[:20]):
            if self._is_low_value_text(page.text):
                continue
            section_title = self._clean_title(self._sentences(page.text)[0] if self._sentences(page.text) else title)
            sections.append(
                {
                    "chapter_number": "1",
                    "chapter_title": title,
                    "section_number": f"1.{len(sections) + 1}",
                    "title": section_title[:80],
                    "source_spans": [SourceSpan(source_file_id=page.source_file_id, source_name=page.source_name, page_start=page.page_number, page_end=page.page_number, text=page.text[:3500])],
                }
            )
            if len(sections) >= 8:
                break
        return sections

    def _dedupe_sections(self, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen = set()
        deduped = []
        for section in sections:
            key = section["section_number"]
            if key in seen:
                continue
            seen.add(key)
            deduped.append(section)
        return deduped[:MAX_OUTLINE_SECTIONS]

    def _section_evidence(self, section: SectionLesson) -> str:
        return "\n\n".join(f"[{span_ref(span)}]\n{span.text}" for span in section.source_spans)

    def support_status(self, answer: str, evidence: str) -> SupportStatus:
        answer_terms = self._terms(answer)
        evidence_terms = self._terms(evidence)
        if not answer_terms:
            return SupportStatus.outside_knowledge
        overlap = len(answer_terms & evidence_terms) / max(1, len(answer_terms))
        if overlap >= 0.45:
            return SupportStatus.pdf_backed
        if overlap >= 0.2:
            return SupportStatus.course_inference
        return SupportStatus.outside_knowledge

    def _fallback_chat_answer(self, question: str, evidence: str) -> str:
        excerpt = self._sentences(evidence)[0] if self._sentences(evidence) else evidence[:240]
        return (
            "PDF-backed: I can answer from the current section evidence. "
            f"For your question, start with this source idea: {excerpt}"
        )

    def _chat(self, system: str, prompt: str) -> str:
        if ollama is None:
            return ""
        try:
            result = ollama.chat(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            )
            return result.get("message", {}).get("content", "").strip()
        except Exception:
            return ""

    def _sentences(self, text: str) -> list[str]:
        normalized = re.sub(r"\s+", " ", text)
        return [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", normalized)
            if 8 <= len(sentence.split()) <= 60 and not self._is_low_value_text(sentence)
        ]

    def _terms(self, text: str) -> set[str]:
        return {
            term
            for term in re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", text.lower())
            if term not in {"the", "and", "for", "that", "this", "with", "from", "are", "you", "your"}
        }

    def _concept_title(self, section_title: str, evidence: str) -> str:
        clean_section_title = re.sub(r"^[0-9]+(?:\.[0-9]+)*\s+", "", section_title).strip()
        if clean_section_title and not self._is_low_value_title(clean_section_title):
            return clean_section_title[:60]
        terms = [term for term in re.findall(r"[A-Za-z][A-Za-z-]{4,}", f"{section_title} {evidence}") if term.lower() not in {"chapter", "section", "example"}]
        if not terms:
            return section_title
        return " ".join(dict.fromkeys(term.title() for term in terms[:2]))

    def _competency_title(self, section_title: str) -> str:
        title = re.sub(r"^(application|practice)\s*:\s*", "", section_title, flags=re.IGNORECASE).strip()
        title = title.replace("/", " and ")
        if title.lower().startswith("introduction to "):
            title = title[len("introduction to "):]
        return f"Master {title}"[:80]

    def _lesson_goal(self, section_title: str) -> str:
        title = self._competency_title(section_title).removeprefix("Master ").strip()
        return (
            f"Learn {title} well enough to explain the idea, solve a straightforward problem, "
            "and recognize when it should be used later in the course."
        )

    def _sync_competency_mastery(self, course: CourseDocument) -> None:
        for competency in course.competencies:
            lesson_sections = [section for section in course.all_sections() if section.id in competency.lesson_ids or competency.id in section.competency_ids]
            concept_scores = [
                concept.mastery.mastery_percent
                for section in lesson_sections
                for concept in section.concepts
                if concept.mastery.mastery_percent > 0
            ]
            check_scores = [
                check.last_score
                for section in lesson_sections
                for check in section.checks
                if check.last_score is not None
            ]
            completion_scores = [100 for section in lesson_sections if section.completed]
            scores = [*concept_scores, *check_scores, *completion_scores]
            if scores:
                competency.mastery.mastery_percent = round(max(competency.mastery.mastery_percent, sum(scores) / len(scores)), 2)
                review_scores = [*concept_scores, *check_scores]
                if review_scores:
                    competency.mastery.last_score = round(sum(review_scores) / len(review_scores), 2)

    def _parse_iso_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed

    def _clean_title(self, value: str) -> str:
        value = re.sub(r"\.{3,}.*$", "", value)
        value = re.sub(r"\s+", " ", value).strip(" -:")
        return value[:90] or "Untitled Section"

    def _is_plausible_section_heading(
        self,
        line: str,
        section_number: str,
        title: str,
        current_chapter_number: str | None,
    ) -> bool:
        if self._is_low_value_title(title):
            return False
        parts = section_number.split(".")
        if len(parts) != 2:
            return False
        chapter_part, section_part = parts
        if current_chapter_number and chapter_part != current_chapter_number:
            return False
        if len(section_part) > 2 or (len(section_part) > 1 and section_part.startswith("0")):
            return False
        if int(section_part) > 30:
            return False
        if re.match(r"^[=×*/]", title):
            return False
        lowered = title.lower()
        if any(marker in lowered for marker in ("our solution", "evaluate ", "simplify.", "answer should contain")):
            return False
        if lowered.startswith(("practice ", "practice-", "review ", "chapter review", "test ")):
            return False
        if re.search(r"\bexample\s+\d+", line, re.IGNORECASE):
            return False
        return True

    def _is_low_value_title(self, title: str) -> bool:
        lowered = title.lower()
        return any(item in lowered for item in ("copyright", "contents", "license", "creative commons", "acknowledg"))

    def _is_low_value_text(self, text: str) -> bool:
        lowered = text.lower()
        compact = re.sub(r"[\s-]+", "", lowered)
        dotted_leaders = len(re.findall(r"\.{4,}\s*\d+", text))
        section_refs = len(re.findall(r"\b\d+\.\d+\b", text))
        phrases = (
            "creative commons",
            "available for free download",
            "table of contents",
            "special thanks",
            "copyright",
            "isbn",
            "faculty reviewers",
            "student reviewers",
            "all rights reserved",
            "some rights reserved",
        )
        compact_phrases = ("creativecommons", "availabelforfreedownload", "tableofcontents", "publicdomain")
        return (
            any(phrase in lowered for phrase in phrases)
            or any(phrase in compact for phrase in compact_phrases)
            or (dotted_leaders >= 4 and section_refs >= 4)
        )


def span_ref(span: SourceSpan) -> str:
    if span.page_start == span.page_end:
        return f"{span.source_name} p. {span.page_start}"
    return f"{span.source_name} pp. {span.page_start}-{span.page_end}"


def build_course_summary(course: CourseDocument) -> dict[str, Any]:
    sections = course.all_sections()
    completed = sum(1 for section in sections if section.completed)
    mastery_source = [competency.mastery.mastery_percent for competency in course.competencies] or [
        concept.mastery.mastery_percent for concept in course.all_concepts()
    ]
    mastery = round(sum(mastery_source) / len(mastery_source), 2) if mastery_source else 0
    next_section = next((section for section in sections if not section.completed), sections[0] if sections else None)
    ready_sections = sum(1 for section in sections if section.status == CourseStatus.ready)
    due_reviews = CourseEngine().due_review_items(course)
    return {
        "course_id": course.course_id,
        "title": course.title,
        "status": course.status.value,
        "competencies_count": len(course.competencies),
        "mastered_competencies": sum(1 for competency in course.competencies if competency.mastery.mastery_percent >= 80),
        "sections_count": len(sections),
        "completed_sections": completed,
        "generated_sections": ready_sections,
        "mastery_percent": mastery,
        "next_section_id": next_section.id if next_section else None,
        "next_section_title": next_section.title if next_section else None,
        "generation_status": course.generation.status.value,
        "generation_completed_sections": course.generation.completed_sections,
        "generation_total_sections": course.generation.total_sections,
        "generation_next_retry_at": course.generation.next_retry_at,
        "generation_last_error": course.generation.last_error,
        "due_reviews_count": len([item for item in due_reviews if item["due"]]),
    }
