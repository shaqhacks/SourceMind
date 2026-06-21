from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

try:
    import ollama
except ImportError:  # pragma: no cover - exercised only when deps are absent.
    ollama = None

from SourceMind.backend.services.lesson_engine import LessonEngine
from SourceMind.backend.services.md_store import Competency, Quote, SRSData, SubjectDocument, SubjectFrontmatter
from SourceMind.backend.services.notebooklm_service import NotebookAnalysis, NotebookCompetency, NotebookQuote


DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")


class GroundingScore(BaseModel):
    grounded_pct: int = Field(ge=0, le=100)
    inference_pct: int = Field(ge=0, le=100)
    prediction_pct: int = Field(ge=0, le=100)
    grounded_quotes: list[str] = Field(default_factory=list)
    rationale: str = ""


class LocalLLMResponse(BaseModel):
    response: str
    grounding: GroundingScore
    model: str


@dataclass(frozen=True)
class SourceEvidence:
    quote_id: str
    text: str
    source_ref: str
    competency_id: str


class LocalLLMService:
    """Ollama-backed local brain with SourceMind Truth Meter metadata."""

    def __init__(self, model: str = DEFAULT_OLLAMA_MODEL) -> None:
        self.model = model

    def generate_study_response(
        self,
        prompt: str,
        quotes: list[Quote],
        mastery_context: dict[str, Any] | None = None,
    ) -> LocalLLMResponse:
        evidence = self._evidence_from_quotes(quotes)
        system_prompt = self._study_system_prompt(evidence, mastery_context or {})
        response = self._chat(system_prompt, prompt) or self._fallback_explanation(prompt, evidence)
        grounding = self.truth_meter(response, evidence, mastery_context or {})
        return LocalLLMResponse(response=response, grounding=grounding, model=self.model)

    def explain_with_critic(
        self,
        question: str,
        quotes: list[Quote],
        mastery_context: dict[str, Any] | None = None,
    ) -> LocalLLMResponse:
        """Generate an explanation and critique it against Markdown ## QUOTES."""

        evidence = self._evidence_from_quotes(quotes)
        system_prompt = self._critic_explanation_prompt(evidence, mastery_context or {})
        response = self._chat(system_prompt, question) or self._fallback_explanation(question, evidence)
        grounding = self.truth_meter(response, evidence, mastery_context or {})
        return LocalLLMResponse(response=response, grounding=grounding, model=self.model)

    def truth_meter(
        self,
        response: str,
        evidence: list[SourceEvidence],
        mastery_context: dict[str, Any] | None = None,
    ) -> GroundingScore:
        heuristic = self._heuristic_grounding(response, evidence)
        llm_score = self._ask_model_for_truth_meter(response, evidence, mastery_context or {})
        if llm_score is None:
            return heuristic

        # Keep the model honest by blending with deterministic quote overlap.
        grounded_pct = round((llm_score.grounded_pct + heuristic.grounded_pct) / 2)
        prediction_pct = max(llm_score.prediction_pct, heuristic.prediction_pct)
        inference_pct = max(0, 100 - grounded_pct - prediction_pct)
        return GroundingScore(
            grounded_pct=grounded_pct,
            inference_pct=inference_pct,
            prediction_pct=prediction_pct,
            grounded_quotes=heuristic.grounded_quotes or llm_score.grounded_quotes,
            rationale=llm_score.rationale or heuristic.rationale,
        )

    def grounding_for_response(
        self,
        response: str,
        quotes: list[Quote],
        mastery_context: dict[str, Any] | None = None,
    ) -> GroundingScore:
        return self.truth_meter(response, self._evidence_from_quotes(quotes), mastery_context)

    def build_subject_from_notebook_analysis(
        self,
        subject_id: str,
        analysis: NotebookAnalysis,
    ) -> SubjectDocument:
        """Convert NotebookLM extraction into SourceMind's Markdown schema."""

        normalized = self._normalize_notebook_analysis(analysis)
        frontmatter = SubjectFrontmatter(
            current_level=1,
            total_mastery=0,
            audio_overview_url=analysis.audio_overview_url,
            understanding_percentages={"level_1": 0, "level_2": 0, "level_3": 0},
        )
        competencies = [
            Competency(
                id=item.id,
                name=item.name,
                level=item.level,
                dependencies=item.dependencies,
                mastery_percent=0,
            )
            for item in normalized.competencies
        ]
        quotes = [
            Quote(
                text=item.text,
                source_ref=item.source_ref,
                competency_id=item.competency_id,
                level_id=item.level_id,
            )
            for item in normalized.quotes
        ]
        srs_data = {competency.id: SRSData() for competency in competencies}
        lesson_bundle = LessonEngine().build_lesson_bundle(competencies, quotes)

        return SubjectDocument(
            subject_id=subject_id,
            frontmatter=frontmatter,
            competencies=competencies,
            quotes=quotes,
            lesson_model=lesson_bundle.lessons,
            worked_examples=lesson_bundle.worked_examples,
            retrieval_checks=lesson_bundle.retrieval_checks,
            misconceptions=lesson_bundle.misconceptions,
            transfer_tasks=lesson_bundle.transfer_tasks,
            lesson_state=lesson_bundle.lesson_state,
            srs_data=srs_data,
            dependencies_notes=self._dependency_notes(normalized.competencies),
            lessons=self._lessons_from_analysis(normalized),
            notes=self._ingestion_notes(analysis),
        )

    def build_subject_markdown_from_notebook_analysis(
        self,
        subject_id: str,
        analysis: NotebookAnalysis,
    ) -> str:
        from SourceMind.backend.services.md_store import MarkdownSubjectStore

        document = self.build_subject_from_notebook_analysis(subject_id, analysis)
        return MarkdownSubjectStore().render(document)

    def _chat(self, system_prompt: str, user_prompt: str) -> str:
        if ollama is None:
            return ""

        try:
            result = ollama.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return result.get("message", {}).get("content", "").strip()
        except Exception:
            return ""

    def _ask_model_for_truth_meter(
        self,
        response: str,
        evidence: list[SourceEvidence],
        mastery_context: dict[str, Any],
    ) -> GroundingScore | None:
        if ollama is None:
            return None

        evidence_text = "\n".join(f"- {item.quote_id}: {item.text}" for item in evidence[:20])
        prompt = f"""
Act as the SourceMind Critic. Compare this explanation against the Markdown ## QUOTES below.

Definitions:
- grounded_pct: claims directly backed 1:1 by a verbatim quote.
- inference_pct: conclusions reasonably derived from the quotes and mastery context.
- prediction_pct: unsupported general knowledge or likely hallucination risk.

Return strict JSON with grounded_pct, inference_pct, prediction_pct, grounded_quotes, rationale.
Percentages must be integers that sum to 100.

Evidence:
{evidence_text}

Mastery context:
{json.dumps(mastery_context, sort_keys=True)}

Response:
{response}
""".strip()
        try:
            result = ollama.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are SourceMind's Truth Meter. Return only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                format="json",
            )
            payload = json.loads(result.get("message", {}).get("content", "{}"))
            return self._normalize_score(payload)
        except Exception:
            return None

    def _normalize_score(self, payload: dict[str, Any]) -> GroundingScore:
        grounded = int(payload.get("grounded_pct", 0))
        inference = int(payload.get("inference_pct", 0))
        prediction = int(payload.get("prediction_pct", 0))
        total = grounded + inference + prediction
        if total <= 0:
            grounded, inference, prediction = 0, 0, 100
        elif total != 100:
            grounded = round(grounded * 100 / total)
            inference = round(inference * 100 / total)
            prediction = max(0, 100 - grounded - inference)

        return GroundingScore(
            grounded_pct=max(0, min(100, grounded)),
            inference_pct=max(0, min(100, inference)),
            prediction_pct=max(0, min(100, prediction)),
            grounded_quotes=[str(item) for item in payload.get("grounded_quotes", [])],
            rationale=str(payload.get("rationale", "")),
        )

    def _heuristic_grounding(self, response: str, evidence: list[SourceEvidence]) -> GroundingScore:
        response_terms = self._terms(response)
        if not response_terms:
            return GroundingScore(grounded_pct=0, inference_pct=0, prediction_pct=100, rationale="Empty response.")

        matched_quotes: list[str] = []
        matched_terms: set[str] = set()
        for item in evidence:
            quote_terms = self._terms(item.text)
            overlap = response_terms & quote_terms
            if len(overlap) >= max(3, min(8, len(quote_terms) // 4)):
                matched_quotes.append(item.quote_id)
                matched_terms.update(overlap)

        grounded_pct = min(100, round(len(matched_terms) * 100 / len(response_terms)))
        prediction_pct = max(0, 100 - grounded_pct - 20) if matched_quotes else 70
        inference_pct = max(0, 100 - grounded_pct - prediction_pct)
        return GroundingScore(
            grounded_pct=grounded_pct,
            inference_pct=inference_pct,
            prediction_pct=prediction_pct,
            grounded_quotes=matched_quotes,
            rationale="Computed from lexical overlap with verbatim subject quotes.",
        )

    def _study_system_prompt(self, evidence: list[SourceEvidence], mastery_context: dict[str, Any]) -> str:
        quote_block = "\n".join(f"[{item.quote_id}] {item.text} ({item.source_ref})" for item in evidence[:30])
        return f"""
You are SourceMind, a local study coach.
Use the provided quotes first. Clearly distinguish direct evidence from inference.
Avoid unsupported predictions unless needed.

Mastery context:
{json.dumps(mastery_context, sort_keys=True)}

Verbatim evidence:
{quote_block}
""".strip()

    def _critic_explanation_prompt(self, evidence: list[SourceEvidence], mastery_context: dict[str, Any]) -> str:
        quote_block = "\n".join(f"[{item.quote_id}] {item.text} ({item.source_ref})" for item in evidence[:30])
        return f"""
You are SourceMind's local explanation engine.
Explain the answer using the Markdown ## QUOTES as primary evidence.
When you move beyond a quote, label the move as an inference.
Avoid prediction or outside knowledge unless explicitly necessary.

Mastery context:
{json.dumps(mastery_context, sort_keys=True)}

Markdown ## QUOTES:
{quote_block}
""".strip()

    def _evidence_from_quotes(self, quotes: list[Quote]) -> list[SourceEvidence]:
        return [
            SourceEvidence(
                quote_id=f"{quote.competency_id}:L{quote.level_id}:{index + 1}",
                text=quote.text,
                source_ref=quote.source_ref,
                competency_id=quote.competency_id,
            )
            for index, quote in enumerate(quotes)
        ]

    def _fallback_explanation(self, question: str, evidence: list[SourceEvidence]) -> str:
        if not evidence:
            return (
                "SourceMind could not find any extracted Markdown quotes for this subject. "
                "A grounded explanation is not available yet. Re-upload a text-selectable PDF, run OCR on scanned pages, "
                f"or start Ollama with the configured model ({self.model}) if you want clearly labeled non-source assistance."
            )

        quote_lines = " ".join(f'"{item.text}" ({item.source_ref})' for item in evidence[:3])
        return (
            "The local Ollama model is unavailable, so this fallback explanation is limited to the Markdown quotes. "
            f"For the question '{question}', the available source evidence says: {quote_lines}"
        )

    def _normalize_notebook_analysis(self, analysis: NotebookAnalysis) -> NotebookAnalysis:
        if ollama is None:
            return self._deterministic_analysis_cleanup(analysis)

        prompt = f"""
Convert this NotebookLM extraction into SourceMind JSON.
Rules:
- Keep every quote text verbatim. Do not paraphrase quote text.
- Ensure Level 2 competencies depend on relevant Level 1 competency IDs.
- Return only JSON with competencies and quotes.

Input JSON:
{analysis.model_dump_json()}
""".strip()
        try:
            result = ollama.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You structure study plans. Preserve quote text exactly."},
                    {"role": "user", "content": prompt},
                ],
                format="json",
            )
            payload = json.loads(result.get("message", {}).get("content", "{}"))
            orchestrated = NotebookAnalysis(
                notebook_id=analysis.notebook_id,
                notebook_name=analysis.notebook_name,
                source_id=analysis.source_id,
                source_name=analysis.source_name,
                audio_overview_url=analysis.audio_overview_url,
                audio_overview_id=analysis.audio_overview_id,
                competencies=[NotebookCompetency.model_validate(item) for item in payload.get("competencies", [])],
                quotes=[NotebookQuote.model_validate(item) for item in payload.get("quotes", [])],
                raw={**analysis.raw, "ollama_orchestration": payload},
            )
            return self._deterministic_analysis_cleanup(orchestrated)
        except Exception:
            return self._deterministic_analysis_cleanup(analysis)

    def _deterministic_analysis_cleanup(self, analysis: NotebookAnalysis) -> NotebookAnalysis:
        competencies = list(analysis.competencies)
        if not competencies:
            competencies = [NotebookCompetency(id="L1_1", name="Source Foundations", level=1)]

        cleaned_competencies = []
        for item in competencies:
            cleaned_competencies.append(item)

        competency_ids = {item.id for item in cleaned_competencies}
        default_competency = cleaned_competencies[0]
        cleaned_quotes = []
        seen_quote_text: set[str] = set()
        for quote in analysis.quotes:
            if self._is_low_value_quote(quote.text):
                continue
            if quote.text in seen_quote_text:
                continue
            seen_quote_text.add(quote.text)
            competency_id = quote.competency_id if quote.competency_id in competency_ids else default_competency.id
            level = next((item.level for item in cleaned_competencies if item.id == competency_id), default_competency.level)
            cleaned_quotes.append(quote.model_copy(update={"competency_id": competency_id, "level_id": level}))

        return analysis.model_copy(update={"competencies": cleaned_competencies, "quotes": cleaned_quotes})

    def _is_low_value_quote(self, text: str) -> bool:
        lowered = text.lower()
        compact = re.sub(r"[\s-]+", "", lowered)
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
            return True
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
            return True
        if re.search(r"\.{4,}", text):
            return True
        terms = self._terms(text)
        return len(terms) < 3

    def _dependency_notes(self, competencies: list[NotebookCompetency]) -> str:
        lines = []
        by_id = {item.id: item for item in competencies}
        for competency in competencies:
            if competency.level < 2:
                continue
            dependency_names = [by_id[item].name if item in by_id else item for item in competency.dependencies]
            if dependency_names:
                lines.append(f"- {competency.id} ({competency.name}) requires: {', '.join(dependency_names)}.")
            else:
                lines.append(f"- {competency.id} ({competency.name}) has no generated Level 1 prerequisite.")
        return "\n".join(lines) if lines else "- No Level 2 dependencies were generated."

    def _lessons_from_analysis(self, analysis: NotebookAnalysis) -> str:
        quotes_by_competency: dict[str, list[NotebookQuote]] = {}
        for quote in analysis.quotes:
            quotes_by_competency.setdefault(quote.competency_id, []).append(quote)

        blocks = []
        for competency in analysis.competencies:
            bloom = self._bloom_label(competency.level)
            quote_lines = [
                f"- Quote ({quote.source_ref}): \"{quote.text}\""
                for quote in quotes_by_competency.get(competency.id, [])[:5]
            ]
            if not quote_lines:
                quote_lines = ["- No verbatim quote extracted yet; keep this competency locked until evidence is added."]
            task = (
                "Recall the quote verbatim and identify the source page."
                if competency.level == 1
                else "Apply the quoted idea to a rewritten scenario and name the prerequisite quote used."
            )
            blocks.append(
                "\n".join(
                    [
                        f"### {competency.id}: {competency.name}",
                        f"- Level: {competency.level}",
                        f"- Bloom alignment: {bloom}",
                        f"- Study task: {task}",
                        *quote_lines,
                    ]
                )
            )
        return "\n\n".join(blocks)

    def _bloom_label(self, level: int) -> str:
        if level <= 1:
            return "Remembering and Understanding"
        if level == 2:
            return "Applying and Analyzing"
        return "Evaluating and Creating"

    def _ingestion_notes(self, analysis: NotebookAnalysis) -> str:
        details = [
            "## INGESTION_METADATA:",
            f"- notebook_id: {analysis.notebook_id or 'local_fallback'}",
            f"- source_id: {analysis.source_id or 'local_fallback'}",
        ]
        if analysis.audio_overview_id:
            details.append(f"- audio_overview_id: {analysis.audio_overview_id}")
        if analysis.raw.get("fallback"):
            details.append("- extraction_mode: local_pdf_fallback")
        return "\n".join(details)

    def _terms(self, text: str) -> set[str]:
        return {term for term in re.findall(r"[a-zA-Z][a-zA-Z0-9'-]{2,}", text.lower()) if term not in STOPWORDS}


STOPWORDS = {
    "and",
    "are",
    "but",
    "for",
    "from",
    "has",
    "have",
    "into",
    "not",
    "that",
    "the",
    "their",
    "this",
    "was",
    "with",
    "you",
    "your",
}
