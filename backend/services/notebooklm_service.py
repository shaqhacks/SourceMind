from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import google.auth
from google.auth.transport.requests import Request
import httpx
from pydantic import BaseModel, Field
from pypdf import PdfReader


class NotebookGroundingResult(BaseModel):
    grounded_quotes: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class AudioOverviewResult(BaseModel):
    audio_overview_url: str | None = None
    audio_overview_id: str | None = None
    status: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class NotebookCompetency(BaseModel):
    id: str
    name: str
    level: int
    dependencies: list[str] = Field(default_factory=list)
    rationale: str = ""


class NotebookQuote(BaseModel):
    text: str
    source_ref: str
    competency_id: str
    level_id: int


class NotebookAnalysis(BaseModel):
    notebook_id: str | None = None
    notebook_name: str | None = None
    source_id: str | None = None
    source_name: str | None = None
    audio_overview_url: str | None = None
    audio_overview_id: str | None = None
    competencies: list[NotebookCompetency] = Field(default_factory=list)
    quotes: list[NotebookQuote] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class NotebookLMService:
    """NotebookLM Enterprise API bridge.

    Official public docs currently cover notebook creation, source upload, source
    retrieval, and audio overview creation. The competency/evidence extraction
    step is exposed here as an adapter: if NOTEBOOKLM_ANALYSIS_PATH is provided,
    SourceMind calls that endpoint; otherwise it falls back to deterministic
    local PDF extraction so uploads remain usable in development.
    """

    def __init__(
        self,
        project_number: str | None = None,
        location: str | None = None,
        endpoint_location: str | None = None,
        api_key: str | None = None,
        timeout: float = 60.0,
        analysis_path: str | None = None,
    ) -> None:
        self.project_number = project_number or os.getenv("GOOGLE_CLOUD_PROJECT_NUMBER", "")
        self.location = location or os.getenv("NOTEBOOKLM_LOCATION", "global")
        self.endpoint_location = endpoint_location or os.getenv("NOTEBOOKLM_ENDPOINT_LOCATION", "global")
        self.api_key = api_key or os.getenv("NOTEBOOKLM_API_KEY")
        self.timeout = timeout
        self.analysis_path = analysis_path or os.getenv("NOTEBOOKLM_ANALYSIS_PATH", "")
        self._access_token: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.project_number)

    @property
    def api_root(self) -> str:
        prefix = "" if self.endpoint_location == "global" else f"{self.endpoint_location}-"
        return f"https://{prefix}discoveryengine.googleapis.com/v1alpha"

    @property
    def upload_root(self) -> str:
        prefix = "" if self.endpoint_location == "global" else f"{self.endpoint_location}-"
        return f"https://{prefix}discoveryengine.googleapis.com/upload/v1alpha"

    @property
    def notebook_collection_path(self) -> str:
        return f"/projects/{self.project_number}/locations/{self.location}/notebooks"

    async def ingest_pdf(self, pdf_path: Path, title: str) -> NotebookAnalysis:
        return await self.ingest_pdfs([pdf_path], title)

    async def ingest_pdfs(self, pdf_paths: list[Path], title: str) -> NotebookAnalysis:
        notebook_payload: dict[str, Any] = {}
        source_payloads: list[dict[str, Any]] = []
        audio = AudioOverviewResult()

        if self.configured:
            notebook_payload = await self.create_notebook(title)
            notebook_id = self._extract_notebook_id(notebook_payload)
            source_ids: list[str] = []
            for pdf_path in pdf_paths:
                source_payload = await self.upload_pdf_source(notebook_id, pdf_path, pdf_path.name)
                source_payloads.append(source_payload)
                source_id = self._extract_source_id(source_payload)
                if source_id:
                    source_ids.append(source_id)
            audio = await self.create_audio_overview(
                notebook_id=notebook_id,
                source_ids=source_ids,
                episode_focus=(
                    "Create an evidence-grounded study overview emphasizing foundational recall, "
                    "applied transfer, and prerequisite relationships."
                ),
            )
        else:
            notebook_id = None
            source_ids = []

        analysis = await self.request_learning_plan(
            pdf_paths=pdf_paths,
            notebook_id=notebook_id,
            source_ids=source_ids,
            title=title,
        )
        analysis.notebook_id = notebook_id
        analysis.notebook_name = notebook_payload.get("name")
        analysis.source_id = source_ids[0] if source_ids else None
        analysis.source_name = source_payloads[0].get("name") if source_payloads else None
        analysis.audio_overview_id = audio.audio_overview_id
        analysis.audio_overview_url = audio.audio_overview_url
        analysis.raw.update(
            {
                "notebook": notebook_payload,
                "sources": source_payloads,
                "audio_overview": audio.raw,
                "configured": self.configured,
            }
        )
        return analysis

    async def create_notebook(self, title: str) -> dict[str, Any]:
        if not self.configured:
            return {"status": "not_configured"}

        return await self._post_json(self.api_root, self.notebook_collection_path, {"title": title})

    async def upload_pdf_source(self, notebook_id: str, pdf_path: Path, display_name: str) -> dict[str, Any]:
        if not self.configured:
            return {"status": "not_configured"}

        path = f"{self.notebook_collection_path}/{notebook_id}/sources:uploadFile"
        headers = {
            "Content-Type": "application/pdf",
            "X-Goog-Upload-File-Name": display_name,
            "X-Goog-Upload-Protocol": "raw",
        }
        return await self._post_bytes(self.upload_root, path, pdf_path.read_bytes(), headers)

    async def create_audio_overview(
        self,
        notebook_id: str,
        source_ids: list[str] | None = None,
        episode_focus: str = "",
        language_code: str = "en-US",
    ) -> AudioOverviewResult:
        if not self.configured:
            return AudioOverviewResult(raw={"status": "not_configured"})

        payload = {
            "sourceIds": [{"id": source_id} for source_id in source_ids or []],
            "episodeFocus": episode_focus,
            "languageCode": language_code,
        }
        data = await self._post_json(
            self.api_root,
            f"{self.notebook_collection_path}/{notebook_id}/audioOverviews",
            payload,
        )
        overview = data.get("audioOverview", data)
        return AudioOverviewResult(
            audio_overview_url=overview.get("audioOverviewUrl") or overview.get("url"),
            audio_overview_id=overview.get("audioOverviewId"),
            status=overview.get("status"),
            raw=data,
        )

    async def request_learning_plan(
        self,
        pdf_paths: list[Path],
        notebook_id: str | None,
        source_ids: list[str],
        title: str,
    ) -> NotebookAnalysis:
        if self.configured and self.analysis_path:
            payload = {
                "notebook_id": notebook_id,
                "source_ids": source_ids,
                "prompt": self.learning_plan_prompt(),
            }
            data = await self._post_json(self.api_root, self.analysis_path, payload)
            return self._analysis_from_payload(data)

        return self._fallback_pdf_analysis(pdf_paths, title)

    def learning_plan_prompt(self) -> str:
        return (
            "Identify Core Competencies from the uploaded PDF. Categorize each competency into Level 1 "
            "(Foundational recall) or Level 2 (Applied transfer). For each competency, extract 3-5 "
            "verbatim quotes with page references. Preserve quote text exactly as it appears in the source. "
            "Return JSON with competencies[{id,name,level,dependencies,rationale}] and "
            "quotes[{text,source_ref,competency_id,level_id}]."
        )

    async def extract_grounded_quotes(self, subject_id: str, markdown: str) -> NotebookGroundingResult:
        if not self.configured:
            return NotebookGroundingResult(raw={"status": "not_configured"})

        payload = {"subject_id": subject_id, "markdown": markdown}
        data = await self._post_json(self.api_root, "/sources:ground", payload)
        return NotebookGroundingResult(
            grounded_quotes=[str(item) for item in data.get("grounded_quotes", [])],
            source_refs=[str(item) for item in data.get("source_refs", [])],
            raw=data,
        )

    async def get_audio_overview(self, subject_id: str) -> AudioOverviewResult:
        if not self.configured:
            return AudioOverviewResult(raw={"status": "not_configured"})

        data = await self._post_json(self.api_root, f"{self.notebook_collection_path}/{subject_id}/audioOverviews", {})
        overview = data.get("audioOverview", data)
        return AudioOverviewResult(
            audio_overview_url=overview.get("audioOverviewUrl") or overview.get("url"),
            audio_overview_id=overview.get("audioOverviewId"),
            status=overview.get("status"),
            raw=data,
        )

    async def _post_json(self, root: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        headers.update(self._auth_headers())

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{root}{path}", json=payload, headers=headers)
            response.raise_for_status()
            return self._json_dict(response)

    async def _post_bytes(self, root: str, path: str, payload: bytes, headers: dict[str, str]) -> dict[str, Any]:
        request_headers = dict(headers)
        request_headers.update(self._auth_headers())

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{root}{path}", content=payload, headers=request_headers)
            response.raise_for_status()
            return self._json_dict(response)

    def _auth_headers(self) -> dict[str, str]:
        bearer_token = self.api_key or self._google_access_token()
        return {"Authorization": f"Bearer {bearer_token}"} if bearer_token else {}

    def _google_access_token(self) -> str | None:
        if self._access_token:
            return self._access_token

        try:
            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            credentials.refresh(Request())
            self._access_token = credentials.token
            return self._access_token
        except Exception:
            return None

    def _json_dict(self, response: httpx.Response) -> dict[str, Any]:
        data = response.json()
        return data if isinstance(data, dict) else {"data": data}

    def _extract_notebook_id(self, payload: dict[str, Any]) -> str:
        notebook_id = payload.get("notebookId")
        if notebook_id:
            return str(notebook_id)
        name = str(payload.get("name", ""))
        return name.rstrip("/").split("/")[-1]

    def _extract_source_id(self, payload: dict[str, Any]) -> str | None:
        source_id = payload.get("sourceId", {})
        if isinstance(source_id, dict) and source_id.get("id"):
            return str(source_id["id"])
        if isinstance(source_id, str):
            return source_id
        return None

    def _analysis_from_payload(self, payload: dict[str, Any]) -> NotebookAnalysis:
        return NotebookAnalysis(
            competencies=[NotebookCompetency.model_validate(item) for item in payload.get("competencies", [])],
            quotes=[NotebookQuote.model_validate(item) for item in payload.get("quotes", [])],
            raw={"analysis": payload},
        )

    def _fallback_pdf_analysis(self, pdf_paths: Path | list[Path], title: str) -> NotebookAnalysis:
        paths = [pdf_paths] if isinstance(pdf_paths, Path) else pdf_paths
        pages = self._extract_pages_from_paths(paths)
        candidates = self._quote_candidates(pages)
        subject_terms = self._subject_terms(title, pages, candidates)
        competencies = self._fallback_competencies(subject_terms, len(candidates))

        quotes: list[NotebookQuote] = []
        for index, quote in enumerate(candidates[: max(3, min(10, len(candidates)))]):
            competency = competencies[index % len(competencies)]
            quotes.append(
                NotebookQuote(
                    text=quote["text"],
                    source_ref=quote["source_ref"],
                    competency_id=competency.id,
                    level_id=competency.level,
                )
            )

        return NotebookAnalysis(
            competencies=competencies,
            quotes=quotes,
            raw={"fallback": True, "pages_extracted": len(pages)},
        )

    def _fallback_competencies(self, subject_terms: list[str], quote_count: int) -> list[NotebookCompetency]:
        if quote_count <= 0:
            return [NotebookCompetency(id="L1_1", name="Source Foundations", level=1)]

        subject = self._subject_label(subject_terms)
        if quote_count == 1:
            return [NotebookCompetency(id="L1_1", name=f"Core {subject} Idea", level=1)]

        level1_count = 2 if quote_count >= 3 else 1
        lesson_names = [
            f"Core {subject} Concepts",
            f"{subject} Procedures and Examples",
        ][:level1_count]
        level1 = [
            NotebookCompetency(
                id=f"L1_{index + 1}",
                name=name,
                level=1,
            )
            for index, name in enumerate(lesson_names)
        ]
        return [
            *level1,
            NotebookCompetency(
                id="L2_1",
                name=f"Apply {subject} to New Problems",
                level=2,
                dependencies=[item.id for item in level1],
            ),
        ]

    def _extract_pages(self, pdf_path: Path) -> list[tuple[int, str]]:
        return [(page_number, text) for _, page_number, text in self._extract_pages_from_paths([pdf_path])]

    def _extract_pages_from_paths(self, pdf_paths: list[Path]) -> list[tuple[str, int, str]]:
        all_pages: list[tuple[str, int, str]] = []
        for pdf_path in pdf_paths:
            all_pages.extend(
                (pdf_path.name, page_number, text)
                for page_number, text in self._extract_pages_single(pdf_path)
            )
        return all_pages

    def _extract_pages_single(self, pdf_path: Path) -> list[tuple[int, str]]:
        reader = PdfReader(str(pdf_path))
        pages: list[tuple[int, str]] = []
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            cleaned = re.sub(r"\s+", " ", text).strip()
            if cleaned:
                pages.append((index, cleaned))
        return pages

    def _quote_candidates(self, pages: list[tuple[int, str]] | list[tuple[str, int, str]]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for page in pages:
            if len(page) == 2:
                source_name = ""
                page_number, text = page
            else:
                source_name, page_number, text = page
            sentences = re.split(r"(?<=[.!?])\s+", text)
            page_candidates = 0
            for sentence in sentences:
                sentence = sentence.strip()
                words = sentence.split()
                if 8 <= len(words) <= 42 and not sentence.endswith(":") and not self._is_low_value_text(sentence):
                    candidates.append(
                        {
                            "page": page_number,
                            "source_ref": self._source_ref(source_name, page_number),
                            "text": sentence,
                            "score": self._instructional_score(sentence, page_number),
                        }
                    )
                    page_candidates += 1
            if page_candidates == 0:
                candidates.extend(self._quote_chunks(page_number, text, source_name))
        return sorted(candidates, key=lambda item: (-item["score"], item["page"], item["text"]))

    def _quote_chunks(self, page_number: int, text: str, source_name: str = "") -> list[dict[str, Any]]:
        words = text.split()
        chunks: list[dict[str, Any]] = []
        for start in range(0, min(len(words), 180), 28):
            chunk_words = words[start : start + 28]
            if len(chunk_words) < 8:
                continue
            chunk = " ".join(chunk_words)
            if self._is_low_value_text(chunk):
                continue
            chunks.append(
                {
                    "page": page_number,
                    "source_ref": self._source_ref(source_name, page_number),
                    "text": chunk,
                    "score": self._instructional_score(chunk, page_number),
                }
            )
            if len(chunks) >= 3:
                break
        return chunks

    def _subject_terms(
        self,
        title: str,
        pages: list[tuple[int, str]] | list[tuple[str, int, str]],
        candidates: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        candidate_text = " ".join(item["text"] for item in (candidates or [])[:12])
        if not candidate_text:
            candidate_text = " ".join(page[-1] for page in pages[:5])
        text = f"{title} {candidate_text}"
        terms = [
            term.lower()
            for term in re.findall(r"[A-Za-z][A-Za-z-]{5,}", text)
            if term.lower() not in FALLBACK_STOPWORDS
        ]
        ranked = sorted(set(terms), key=lambda term: (-terms.count(term), term))
        return ranked[:4]

    def _subject_label(self, subject_terms: list[str]) -> str:
        if not subject_terms:
            return "Source"
        if "algebra" in subject_terms:
            return "Algebra"
        if "addition" in subject_terms:
            return "Addition"
        if "subtraction" in subject_terms:
            return "Subtraction"
        return " ".join(term.title() for term in subject_terms[:2])

    def _source_ref(self, source_name: str, page_number: int) -> str:
        return f"{source_name} p. {page_number}" if source_name else f"p. {page_number}"

    def _is_low_value_text(self, text: str) -> bool:
        lowered = text.lower()
        compact = re.sub(r"[\s-]+", "", lowered)
        low_value_phrases = (
            "creative commons",
            "all rights reserved",
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
        alpha_words = re.findall(r"[a-zA-Z]{3,}", text)
        if len(alpha_words) < 6:
            return True
        if len(re.findall(r"\.{4,}", text)) > 0:
            return True
        return False

    def _instructional_score(self, text: str, page_number: int) -> int:
        lowered = text.lower()
        score = 0
        instructional_terms = (
            "definition",
            "equation",
            "expression",
            "integer",
            "variable",
            "solution",
            "solve",
            "property",
            "example",
            "factor",
            "graph",
            "function",
            "fraction",
            "addition",
            "subtraction",
            "multiplication",
            "division",
            "negative",
            "positive",
            "absolute",
            "simplify",
            "evaluate",
        )
        score += sum(4 for term in instructional_terms if term in lowered)
        if re.search(r"\b(is|are|means|called|represents|equals)\b", lowered):
            score += 3
        if page_number > 5:
            score += 2
        return score


FALLBACK_STOPWORDS = {
    "abstract",
    "because",
    "between",
    "chapter",
    "figure",
    "rights",
    "wallace",
    "available",
    "download",
    "textbook",
    "license",
    "licensed",
    "creative",
    "commons",
    "copyright",
    "contents",
    "beginning",
    "intermediate",
    "learning",
    "should",
    "source",
    "through",
    "within",
}
