from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, Field

from SourceMind.backend.services.llm_local import GroundingScore
from SourceMind.backend.services.md_store import Competency, Quote, SRSData, SubjectDocument


MASTERY_GATE_PERCENT = 80.0
HIGH_CONFIDENCE_MIN = 5
LEVEL2_FAILURE_THRESHOLD = 3


class StudyMode(str, Enum):
    foundation = "foundation"
    transfer = "transfer"


class StudyItem(BaseModel):
    competency_id: str
    competency_name: str
    level: int
    mode: StudyMode
    prompt: str
    quote: Quote | None = None
    priority: int
    blocked: bool = False
    blocked_by: list[str] = Field(default_factory=list)
    due_reason: str
    repetitions_completed: int = 0


class StudySession(BaseModel):
    subject_id: str
    items: list[StudyItem]
    blocked_items: list[StudyItem] = Field(default_factory=list)
    mastery_gate: dict[str, list[str]] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    subject_id: str
    competency_id: str
    correct: bool
    confidence: int = Field(ge=1, le=6)
    score: float = Field(ge=0, le=100)
    mastery_percent: float = Field(ge=0, le=100)
    ease: float
    interval: int
    prioritized_for_immediate_repeat: bool
    penalty_halved_for_prediction_risk: bool
    diagnostic_downshift: dict[str, str] | None = None


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    blocked_by: list[str]


class SRSEngine:
    """Price-style confidence-aware SRS plus vertical transfer gating."""

    def build_session(self, document: SubjectDocument, limit: int = 10) -> StudySession:
        items: list[StudyItem] = []
        blocked_items: list[StudyItem] = []
        mastery_gate: dict[str, list[str]] = {}

        for competency in document.competencies:
            srs = self._srs_for(document, competency.id)
            gate = self.mastery_gate(document, competency)
            quote = self._quote_for(document, competency)
            item = self._build_item(competency, srs, quote, gate)
            if item.blocked:
                blocked_items.append(item)
                mastery_gate[competency.id] = item.blocked_by
            else:
                items.append(item)

        items.sort(key=lambda item: item.priority, reverse=True)
        return StudySession(
            subject_id=document.subject_id,
            items=items[:limit],
            blocked_items=blocked_items,
            mastery_gate=mastery_gate,
        )

    def evaluate(
        self,
        document: SubjectDocument,
        competency_id: str,
        correct: bool,
        confidence: int,
        grounding: GroundingScore | None = None,
        level: int | None = None,
    ) -> EvaluationResult:
        if confidence < 1 or confidence > 6:
            raise ValueError("confidence must be between 1 and 6")

        competency = self._competency_by_id(document, competency_id)
        active_level = level or competency.level
        srs = self._srs_for(document, competency_id)
        srs.confidence_history.append(confidence)
        srs.repetitions += 1

        incorrect_but_confident = not correct and confidence >= HIGH_CONFIDENCE_MIN
        penalty_halved = bool(grounding and grounding.prediction_pct > 30 and not correct)

        score = self._score(correct, confidence)
        old_mastery = competency.mastery_percent
        competency.mastery_percent = self._updated_mastery(old_mastery, correct, confidence, penalty_halved)
        srs.last_score = score
        srs.ease = self._updated_ease(srs.ease, correct, confidence, incorrect_but_confident, penalty_halved)
        srs.interval = self._next_interval(srs, correct, incorrect_but_confident, penalty_halved)

        if correct:
            srs.failure_streak = 0
            if active_level >= 2:
                srs.level2_failure_streak = 0
        else:
            srs.failure_streak += 1
            if active_level >= 2:
                srs.level2_failure_streak += 1

        document.srs_data[competency_id] = srs
        document.frontmatter.total_mastery = self._total_mastery(document)
        document.frontmatter.understanding_percentages = self._understanding_percentages(document)

        return EvaluationResult(
            subject_id=document.subject_id,
            competency_id=competency_id,
            correct=correct,
            confidence=confidence,
            score=score,
            mastery_percent=competency.mastery_percent,
            ease=srs.ease,
            interval=srs.interval,
            prioritized_for_immediate_repeat=incorrect_but_confident,
            penalty_halved_for_prediction_risk=penalty_halved,
            diagnostic_downshift=self.diagnostic_downshift(document, competency) if not correct else None,
        )

    def mastery_gate(self, document: SubjectDocument, competency: Competency) -> GateResult:
        if competency.level < 2:
            return GateResult(allowed=True, blocked_by=[])

        blocked_by = []
        by_id = {item.id: item for item in document.competencies}
        for dependency_id in competency.dependencies:
            dependency = by_id.get(dependency_id)
            if dependency is None or dependency.mastery_percent < MASTERY_GATE_PERCENT:
                blocked_by.append(dependency_id)

        return GateResult(allowed=not blocked_by, blocked_by=blocked_by)

    def diagnostic_downshift(self, document: SubjectDocument, competency: Competency) -> dict[str, str] | None:
        srs = self._srs_for(document, competency.id)
        if competency.level < 2 or srs.level2_failure_streak < LEVEL2_FAILURE_THRESHOLD:
            return None

        prerequisite_id = competency.dependencies[0] if competency.dependencies else ""
        prerequisite_quote = self._quote_for_id(document, prerequisite_id)
        if not prerequisite_id:
            return None

        suggestion = "Return to the Level 1 prerequisite before attempting this transfer again."
        if prerequisite_quote:
            suggestion = f'Return to Level 1 prerequisite {prerequisite_id}: "{prerequisite_quote.text}"'

        return {
            "type": "socratic_remediation",
            "competency_id": competency.id,
            "prerequisite_id": prerequisite_id,
            "suggestion": suggestion,
        }

    def _build_item(self, competency: Competency, srs: SRSData, quote: Quote | None, gate: GateResult) -> StudyItem:
        incorrect_but_confident = srs.last_score is not None and srs.last_score < 60 and self._last_confidence(srs) >= 5
        needs_double_repeat = srs.repetitions < 2 or len(srs.confidence_history) < 2
        priority = 100
        reasons = []

        if incorrect_but_confident:
            priority += 1000
            reasons.append("incorrect_but_confident")
        if needs_double_repeat:
            priority += 300
            reasons.append("needs_double_repetition")
        priority += max(0, 100 - round(competency.mastery_percent))
        priority -= min(200, srs.interval * 10)

        mode = StudyMode.foundation if competency.level == 1 else StudyMode.transfer
        prompt = self._prompt_for(competency, quote, mode)
        return StudyItem(
            competency_id=competency.id,
            competency_name=competency.name,
            level=competency.level,
            mode=mode,
            prompt=prompt,
            quote=quote,
            priority=priority,
            blocked=not gate.allowed,
            blocked_by=gate.blocked_by,
            due_reason=", ".join(reasons) if reasons else "standard_review",
            repetitions_completed=srs.repetitions,
        )

    def _prompt_for(self, competency: Competency, quote: Quote | None, mode: StudyMode) -> str:
        if mode == StudyMode.foundation:
            if quote:
                return f"Recall the verbatim source idea for {competency.name} from {quote.source_ref}."
            return f"Recall the foundational idea for {competency.name}."
        return f"Apply {competency.name} to a new scenario while preserving the source-grounded logic."

    def _score(self, correct: bool, confidence: int) -> float:
        if correct:
            return min(100, 70 + confidence * 5)
        return max(0, 45 - confidence * 5)

    def _updated_mastery(self, current: float, correct: bool, confidence: int, penalty_halved: bool) -> float:
        if correct:
            delta = 4 + confidence
        else:
            delta = -(6 + confidence * 2)
            if penalty_halved:
                delta /= 2
        return max(0, min(100, round(current + delta, 2)))

    def _updated_ease(
        self,
        current: float,
        correct: bool,
        confidence: int,
        incorrect_but_confident: bool,
        penalty_halved: bool,
    ) -> float:
        if correct:
            delta = 0.08 + confidence * 0.01
        elif incorrect_but_confident:
            delta = -0.35
        else:
            delta = -0.18
        if penalty_halved and delta < 0:
            delta /= 2
        return max(1.3, round(current + delta, 2))

    def _next_interval(
        self,
        srs: SRSData,
        correct: bool,
        incorrect_but_confident: bool,
        penalty_halved: bool,
    ) -> int:
        if incorrect_but_confident:
            return 0
        if not correct:
            return max(0, srs.interval // 2) if penalty_halved else 0
        if srs.repetitions < 2:
            return 1
        return max(1, round(max(1, srs.interval) * srs.ease))

    def _total_mastery(self, document: SubjectDocument) -> float:
        if not document.competencies:
            return 0
        return round(sum(item.mastery_percent for item in document.competencies) / len(document.competencies), 2)

    def _understanding_percentages(self, document: SubjectDocument) -> dict[str, float]:
        levels = sorted({item.level for item in document.competencies})
        percentages: dict[str, float] = {}
        for level in levels:
            level_items = [item for item in document.competencies if item.level == level]
            percentages[f"level_{level}"] = round(
                sum(item.mastery_percent for item in level_items) / len(level_items),
                2,
            )
        return percentages

    def _srs_for(self, document: SubjectDocument, competency_id: str) -> SRSData:
        srs = document.srs_data.get(competency_id)
        if srs is None:
            srs = SRSData()
            document.srs_data[competency_id] = srs
        return srs

    def _competency_by_id(self, document: SubjectDocument, competency_id: str) -> Competency:
        for competency in document.competencies:
            if competency.id == competency_id:
                return competency
        raise KeyError(f"Unknown competency_id: {competency_id}")

    def _quote_for(self, document: SubjectDocument, competency: Competency) -> Quote | None:
        return self._quote_for_id(document, competency.id)

    def _quote_for_id(self, document: SubjectDocument, competency_id: str) -> Quote | None:
        for quote in document.quotes:
            if quote.competency_id == competency_id and self._is_teaching_quote(quote.text):
                return quote
        return None

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

    def _last_confidence(self, srs: SRSData) -> int:
        return srs.confidence_history[-1] if srs.confidence_history else 0
