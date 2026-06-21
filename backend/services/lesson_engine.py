from __future__ import annotations

from dataclasses import dataclass

from SourceMind.backend.services.md_store import (
    Competency,
    Lesson,
    LessonState,
    Misconception,
    Quote,
    RetrievalCheck,
    SubjectDocument,
    TransferTask,
    WorkedExample,
)


BASIC_INTERLEAVING_MASTERY = 60.0
TRANSFER_GATE_MASTERY = 80.0


@dataclass(frozen=True)
class LessonBundle:
    lessons: list[Lesson]
    worked_examples: list[WorkedExample]
    retrieval_checks: list[RetrievalCheck]
    misconceptions: list[Misconception]
    transfer_tasks: list[TransferTask]
    lesson_state: dict[str, LessonState]


class LessonEngine:
    """Build and operate SourceMind's durable lesson model.

    Lessons are generated once from the source-backed competencies and quotes,
    then persisted in Markdown. Runtime study loads this durable model rather
    than asking an LLM to recreate course content on every lesson load.
    """

    def build_lesson_bundle(self, competencies: list[Competency], quotes: list[Quote]) -> LessonBundle:
        quotes_by_competency = self._quotes_by_competency(quotes, usable_only=True)
        level1_ids = [item.id for item in competencies if item.level == 1]
        lessons: list[Lesson] = []
        worked_examples: list[WorkedExample] = []
        retrieval_checks: list[RetrievalCheck] = []
        misconceptions: list[Misconception] = []
        transfer_tasks: list[TransferTask] = []
        lesson_state: dict[str, LessonState] = {}

        for competency in competencies:
            lesson_id = f"LESSON_{competency.id}"
            competency_quotes = quotes_by_competency.get(competency.id, [])
            source_quote_ids = self._quote_ids(competency_quotes)
            worked_example_id = f"WE_{competency.id}_1"
            misconception_id = f"MIS_{competency.id}_1"
            check_ids = [f"RC_{competency.id}_{index}" for index in range(1, 4)]
            transfer_task_id = f"TT_{competency.id}_1"

            status = "ready" if competency_quotes else "needs_review"
            lesson_worked_example_ids: list[str] = []
            lesson_check_ids: list[str] = []
            lesson_misconception_ids: list[str] = []
            transfer_task_ids: list[str] = []

            if competency_quotes:
                worked_examples.append(self._worked_example(worked_example_id, competency, quotes_by_competency))
                retrieval_checks.extend(self._retrieval_checks(competency, quotes_by_competency, check_ids))
                misconceptions.append(self._misconception(misconception_id, competency, quotes_by_competency))
                lesson_worked_example_ids = [worked_example_id]
                lesson_check_ids = check_ids
                lesson_misconception_ids = [misconception_id]

            if competency.level >= 2:
                prerequisites = competency.dependencies
                if not prerequisites:
                    status = "needs_review"
                transfer_tasks.append(
                    TransferTask(
                        id=transfer_task_id,
                        competency_id=competency.id,
                        prompt=(
                            f"Apply {competency.name} to a new scenario. Name the prerequisite concept "
                            "and cite the source idea that supports your reasoning."
                        ),
                        prerequisite_ids=prerequisites,
                        locked=True,
                        interleaving_group=[competency.id, *prerequisites],
                    )
                )
                transfer_task_ids.append(transfer_task_id)

            lessons.append(
                Lesson(
                    id=lesson_id,
                    title=competency.name,
                    competency_id=competency.id,
                    objective=self._objective_for(competency),
                    reading=self._lesson_reading(competency, competency_quotes, quotes_by_competency),
                    status=status,
                    source_quote_ids=source_quote_ids,
                    worked_example_ids=lesson_worked_example_ids,
                    retrieval_check_ids=lesson_check_ids,
                    misconception_ids=lesson_misconception_ids,
                    transfer_task_ids=transfer_task_ids,
                )
            )
            lesson_state[lesson_id] = LessonState()

        return LessonBundle(
            lessons=lessons,
            worked_examples=worked_examples,
            retrieval_checks=retrieval_checks,
            misconceptions=misconceptions,
            transfer_tasks=transfer_tasks,
            lesson_state=lesson_state,
        )

    def ensure_lesson_model(self, document: SubjectDocument) -> SubjectDocument:
        if document.lesson_model:
            self._ensure_lesson_readings(document)
            self.refresh_transfer_locks(document)
            return document

        bundle = self.build_lesson_bundle(document.competencies, document.quotes)
        document.lesson_model = bundle.lessons
        document.worked_examples = bundle.worked_examples
        document.retrieval_checks = bundle.retrieval_checks
        document.misconceptions = bundle.misconceptions
        document.transfer_tasks = bundle.transfer_tasks
        document.lesson_state = bundle.lesson_state
        self.refresh_transfer_locks(document)
        return document

    def lesson_detail(self, document: SubjectDocument, lesson_id: str) -> dict[str, object]:
        self.ensure_lesson_model(document)
        lesson = self._lesson_by_id(document, lesson_id)
        competency = self._competency_by_id(document, lesson.competency_id)
        quote_ids = set(lesson.source_quote_ids)
        worked_ids = set(lesson.worked_example_ids)
        check_ids = set(lesson.retrieval_check_ids)
        misconception_ids = set(lesson.misconception_ids)
        transfer_ids = set(lesson.transfer_task_ids)
        self.refresh_transfer_locks(document)

        related_mastery = [
            item.mastery_percent
            for item in document.competencies
            if item.id == competency.id or item.id in competency.dependencies
        ]
        interleaving_unlocked = bool(related_mastery) and min(related_mastery) >= BASIC_INTERLEAVING_MASTERY
        document.lesson_state.setdefault(lesson.id, LessonState()).interleaving_unlocked = interleaving_unlocked

        return {
            "lesson": lesson,
            "competency": competency,
            "quotes": [quote for quote in document.quotes if self._quote_id(quote) in quote_ids],
            "worked_examples": [item for item in document.worked_examples if item.id in worked_ids],
            "retrieval_checks": [item for item in document.retrieval_checks if item.id in check_ids],
            "misconceptions": [item for item in document.misconceptions if item.id in misconception_ids],
            "transfer_tasks": [item for item in document.transfer_tasks if item.id in transfer_ids],
            "state": document.lesson_state.get(lesson.id, LessonState()),
            "interleaving_unlocked": interleaving_unlocked,
        }

    def update_retrieval_check(
        self,
        document: SubjectDocument,
        lesson_id: str,
        check_id: str,
        correct: bool,
        confidence: int,
        mastery_percent: float,
        interval: int,
    ) -> RetrievalCheck:
        check = self._check_by_id(document, check_id)
        check.confidence_history.append(confidence)
        check.mastery_percent = mastery_percent
        check.interval = interval
        state = document.lesson_state.setdefault(lesson_id, LessonState())
        if correct and check_id not in state.completed_check_ids:
            state.completed_check_ids.append(check_id)
        self.refresh_transfer_locks(document)
        return check

    def refresh_transfer_locks(self, document: SubjectDocument) -> None:
        mastery_by_id = {item.id: item.mastery_percent for item in document.competencies}
        for task in document.transfer_tasks:
            task.locked = not task.prerequisite_ids or any(
                mastery_by_id.get(prerequisite_id, 0) < TRANSFER_GATE_MASTERY
                for prerequisite_id in task.prerequisite_ids
            )
        for lesson in document.lesson_model:
            state = document.lesson_state.setdefault(lesson.id, LessonState())
            unlocked = [
                task.id
                for task in document.transfer_tasks
                if task.id in lesson.transfer_task_ids and not task.locked
            ]
            state.unlocked_transfer_task_ids = unlocked

    def related_quotes_for_lesson(self, document: SubjectDocument, lesson_id: str) -> list[Quote]:
        lesson = self._lesson_by_id(document, lesson_id)
        competency = self._competency_by_id(document, lesson.competency_id)
        ids = {competency.id, *competency.dependencies}
        return [
            quote
            for quote in document.quotes
            if quote.competency_id in ids and self._is_teaching_quote(quote.text)
        ]

    def _worked_example(
        self,
        worked_example_id: str,
        competency: Competency,
        quotes_by_competency: dict[str, list[Quote]],
    ) -> WorkedExample:
        quote = self._required_quote(competency.id, quotes_by_competency)
        steps = [
            f"Start from the source claim for {competency.name}.",
            f"State the idea in your own words while preserving the source meaning: {quote.text}",
            (
                "Use the idea in a simple case before attempting transfer."
                if competency.level == 1
                else "Name the prerequisite concept before applying this to a new case."
            ),
        ]
        return WorkedExample(
            id=worked_example_id,
            competency_id=competency.id,
            prompt=f"Worked example for {competency.name}",
            steps=steps,
            source_quote_ids=[self._quote_id(quote)],
            status="grounded",
        )

    def _retrieval_checks(
        self,
        competency: Competency,
        quotes_by_competency: dict[str, list[Quote]],
        check_ids: list[str],
    ) -> list[RetrievalCheck]:
        quote = self._required_quote(competency.id, quotes_by_competency)
        return [
            RetrievalCheck(
                id=check_ids[0],
                competency_id=competency.id,
                question=f"What is the core idea of {competency.name}?",
                expected_answer=quote.text,
            ),
            RetrievalCheck(
                id=check_ids[1],
                competency_id=competency.id,
                question=f"Which source reference supports {competency.name}?",
                expected_answer=quote.source_ref,
            ),
            RetrievalCheck(
                id=check_ids[2],
                competency_id=competency.id,
                question=f"Explain why {competency.name} matters before using it in a harder problem.",
                expected_answer=f"{competency.name} must be understood before transfer because it is a prerequisite idea.",
            ),
        ]

    def _misconception(
        self,
        misconception_id: str,
        competency: Competency,
        quotes_by_competency: dict[str, list[Quote]],
    ) -> Misconception:
        quote = self._required_quote(competency.id, quotes_by_competency)
        return Misconception(
            id=misconception_id,
            competency_id=competency.id,
            trap=f"Confusing a familiar summary of {competency.name} with the source-backed idea.",
            correction=f"Return to the source wording before applying it: {quote.text}",
            source_quote_ids=[self._quote_id(quote)],
        )

    def _ensure_lesson_readings(self, document: SubjectDocument) -> None:
        quotes_by_competency = self._quotes_by_competency(document.quotes, usable_only=True)
        competencies = {competency.id: competency for competency in document.competencies}
        for lesson in document.lesson_model:
            competency = competencies.get(lesson.competency_id)
            if competency is None:
                continue
            if not quotes_by_competency.get(competency.id):
                lesson.status = "needs_review"
                lesson.reading = self._lesson_reading(competency, [], quotes_by_competency)
                lesson.worked_example_ids = []
                lesson.retrieval_check_ids = []
                lesson.misconception_ids = []
                continue
            if lesson.reading:
                continue
            lesson.reading = self._lesson_reading(
                competency,
                quotes_by_competency.get(competency.id, []),
                quotes_by_competency,
            )

    def _lesson_reading(
        self,
        competency: Competency,
        competency_quotes: list[Quote],
        quotes_by_competency: dict[str, list[Quote]],
    ) -> list[str]:
        if not competency_quotes:
            return [
                (
                    f"This lesson is waiting for usable source evidence for {competency.name}. "
                    "The extracted text looks like front matter, licensing, links, acknowledgements, or a table of "
                    "contents instead of teachable subject material. Re-upload a text-selectable PDF with the actual "
                    "lesson pages, or run OCR if the source is scanned."
                )
            ]

        primary = competency_quotes[0]
        paragraphs = [
            (
                f"This lesson teaches {competency.name}. Start with the source claim from {primary.source_ref}: "
                f"{primary.text}"
            ),
            (
                "Turn the source claim into a usable idea: identify the main term, explain what it means in your own "
                "words, and keep the explanation tied to the quoted evidence instead of guessing."
            ),
        ]

        if competency.level <= 1:
            paragraphs.append(
                "Before moving on, you should be able to recall the idea, point to the supporting source reference, "
                "and explain a simple example without changing the meaning of the source."
            )
        else:
            prerequisite_names = ", ".join(competency.dependencies) if competency.dependencies else "the prerequisite ideas"
            paragraphs.append(
                f"This is a transfer lesson. Apply {competency.name} only after reviewing {prerequisite_names}; "
                "then show how the source-backed idea changes what you do in a new problem."
            )

        supporting_quotes = [
            quote
            for dependency_id in competency.dependencies
            for quote in quotes_by_competency.get(dependency_id, [])[:1]
        ]
        if supporting_quotes:
            evidence = "; ".join(f"{quote.source_ref}: {quote.text}" for quote in supporting_quotes[:2])
            paragraphs.append(f"Prerequisite evidence to keep nearby: {evidence}")

        return paragraphs

    def _objective_for(self, competency: Competency) -> str:
        if competency.level <= 1:
            return f"Recall and explain the source-grounded foundation for {competency.name}."
        return f"Apply {competency.name} only after its prerequisite concepts are mastered."

    def _quotes_by_competency(self, quotes: list[Quote], usable_only: bool = False) -> dict[str, list[Quote]]:
        by_competency: dict[str, list[Quote]] = {}
        for quote in quotes:
            if usable_only and not self._is_teaching_quote(quote.text):
                continue
            by_competency.setdefault(quote.competency_id, []).append(quote)
        return by_competency

    def _is_teaching_quote(self, text: str) -> bool:
        lowered = text.lower()
        compact = "".join(character for character in lowered if not character.isspace() and character != "-")
        low_value_phrases = (
            "creative commons",
            "all rights reserved",
            "some rights reserved",
            "available for free download",
            "table of contents",
            "special thanks",
            "beautiful wife",
            "http://",
            "https://",
            "www.",
            "isbn",
            "copyright",
            "licensed under",
            "public domain",
            "waiver",
            "permission from",
            "faculty reviewers",
            "student reviewers",
            "the text:",
            "reviewed this text",
            "typing problems",
            "patience and support",
        )
        if any(phrase in lowered for phrase in low_value_phrases):
            return False
        if any(
            phrase in compact
            for phrase in (
                "creativecommons",
                "availabelforfreedownload",
                "publicdomain",
                "copyrightholder",
                "licensedunder",
                "applicablelaw",
            )
        ):
            return False
        if "...." in text:
            return False
        return len([word for word in text.split() if len(word.strip(".,;:()[]")) >= 3]) >= 3

    def _quote_ids(self, quotes: list[Quote]) -> list[str]:
        return [self._quote_id(quote) for quote in quotes]

    def _quote_id(self, quote: Quote) -> str:
        return f"{quote.competency_id}:{quote.source_ref}"

    def _required_quote(self, competency_id: str, quotes_by_competency: dict[str, list[Quote]]) -> Quote:
        quotes = quotes_by_competency.get(competency_id)
        if quotes:
            return quotes[0]
        raise ValueError(f"Cannot generate grounded lesson artifact without a quote for {competency_id}")

    def _lesson_by_id(self, document: SubjectDocument, lesson_id: str) -> Lesson:
        for lesson in document.lesson_model:
            if lesson.id == lesson_id:
                return lesson
        raise KeyError(f"Unknown lesson_id: {lesson_id}")

    def _competency_by_id(self, document: SubjectDocument, competency_id: str) -> Competency:
        for competency in document.competencies:
            if competency.id == competency_id:
                return competency
        raise KeyError(f"Unknown competency_id: {competency_id}")

    def _check_by_id(self, document: SubjectDocument, check_id: str) -> RetrievalCheck:
        for check in document.retrieval_checks:
            if check.id == check_id:
                return check
        raise KeyError(f"Unknown check_id: {check_id}")
