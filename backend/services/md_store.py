from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUBJECT_DIR = PROJECT_ROOT / "data" / "subjects"


class Competency(BaseModel):
    id: str
    name: str
    level: int
    dependencies: list[str] = Field(default_factory=list)
    mastery_percent: float = Field(ge=0, le=100)

    @field_validator("id", "name")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be empty")
        return value


class Quote(BaseModel):
    text: str
    source_ref: str
    competency_id: str
    level_id: int

    @field_validator("text", "source_ref", "competency_id")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be empty")
        return value


class Lesson(BaseModel):
    id: str
    title: str
    competency_id: str
    objective: str
    reading: list[str] = Field(default_factory=list)
    status: str = "ready"
    source_quote_ids: list[str] = Field(default_factory=list)
    worked_example_ids: list[str] = Field(default_factory=list)
    retrieval_check_ids: list[str] = Field(default_factory=list)
    misconception_ids: list[str] = Field(default_factory=list)
    transfer_task_ids: list[str] = Field(default_factory=list)

    @field_validator("id", "title", "competency_id", "objective")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be empty")
        return value

    @field_validator("reading")
    @classmethod
    def reading_paragraphs_are_text(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value.strip()]


class WorkedExample(BaseModel):
    id: str
    competency_id: str
    prompt: str
    steps: list[str] = Field(default_factory=list)
    source_quote_ids: list[str] = Field(default_factory=list)
    status: str = "grounded"

    @field_validator("id", "competency_id", "prompt")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be empty")
        return value


class RetrievalCheck(BaseModel):
    id: str
    competency_id: str
    question: str
    expected_answer: str
    difficulty: str = "easy"
    mastery_percent: float = Field(default=0, ge=0, le=100)
    interval: int = Field(default=0, ge=0)
    confidence_history: list[int] = Field(default_factory=list)

    @field_validator("id", "competency_id", "question", "expected_answer")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be empty")
        return value

    @field_validator("confidence_history")
    @classmethod
    def confidence_values_are_one_to_six(cls, values: list[int]) -> list[int]:
        for value in values:
            if value < 1 or value > 6:
                raise ValueError("confidence values must be between 1 and 6")
        return values


class Misconception(BaseModel):
    id: str
    competency_id: str
    trap: str
    correction: str
    source_quote_ids: list[str] = Field(default_factory=list)

    @field_validator("id", "competency_id", "trap", "correction")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be empty")
        return value


class TransferTask(BaseModel):
    id: str
    competency_id: str
    prompt: str
    prerequisite_ids: list[str] = Field(default_factory=list)
    locked: bool = True
    interleaving_group: list[str] = Field(default_factory=list)

    @field_validator("id", "competency_id", "prompt")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be empty")
        return value


class LessonState(BaseModel):
    completed_check_ids: list[str] = Field(default_factory=list)
    unlocked_transfer_task_ids: list[str] = Field(default_factory=list)
    interleaving_unlocked: bool = False
    question_history: list[dict[str, str]] = Field(default_factory=list)


class SRSData(BaseModel):
    ease: float = Field(default=2.5, gt=0)
    interval: int = Field(default=0, ge=0)
    last_score: float | None = Field(default=None, ge=0, le=100)
    confidence_history: list[int] = Field(default_factory=list)
    repetitions: int = Field(default=0, ge=0)
    failure_streak: int = Field(default=0, ge=0)
    level2_failure_streak: int = Field(default=0, ge=0)

    @field_validator("confidence_history")
    @classmethod
    def confidence_values_are_one_to_six(cls, values: list[int]) -> list[int]:
        for value in values:
            if value < 1 or value > 6:
                raise ValueError("confidence values must be between 1 and 6")
        return values


class SubjectFrontmatter(BaseModel):
    current_level: int = 1
    total_mastery: float = Field(default=0, ge=0, le=100)
    audio_overview_url: str | None = None
    understanding_percentages: dict[str, float] = Field(default_factory=dict)

    @field_validator("understanding_percentages")
    @classmethod
    def percentages_are_valid(cls, values: dict[str, float]) -> dict[str, float]:
        for key, value in values.items():
            if value < 0 or value > 100:
                raise ValueError(f"understanding percentage for {key!r} must be 0-100")
        return values


class SubjectDocument(BaseModel):
    subject_id: str
    frontmatter: SubjectFrontmatter = Field(default_factory=SubjectFrontmatter)
    competencies: list[Competency] = Field(default_factory=list)
    quotes: list[Quote] = Field(default_factory=list)
    lesson_model: list[Lesson] = Field(default_factory=list)
    worked_examples: list[WorkedExample] = Field(default_factory=list)
    retrieval_checks: list[RetrievalCheck] = Field(default_factory=list)
    misconceptions: list[Misconception] = Field(default_factory=list)
    transfer_tasks: list[TransferTask] = Field(default_factory=list)
    lesson_state: dict[str, LessonState] = Field(default_factory=dict)
    srs_data: dict[str, SRSData] = Field(default_factory=dict)
    dependencies_notes: str = ""
    lessons: str = ""
    notes: str = ""


@dataclass(frozen=True)
class MarkdownSections:
    frontmatter: dict[str, Any] = field(default_factory=dict)
    body: str = ""


class MarkdownSubjectStore:
    """Read and write SourceMind subject Markdown files.

    The store intentionally keeps persistence as local Markdown. It parses the
    structured sections into Pydantic models so learning engines can work with
    typed data without introducing a database.
    """

    _frontmatter_re = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
    _heading_re = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)

    def __init__(self, subject_dir: Path | str = DEFAULT_SUBJECT_DIR) -> None:
        self.subject_dir = Path(subject_dir)
        self.subject_dir.mkdir(parents=True, exist_ok=True)

    def list_subject_ids(self) -> list[str]:
        return sorted(path.stem for path in self.subject_dir.glob("*.md"))

    def subject_path(self, subject_id: str) -> Path:
        safe_id = self._validate_subject_id(subject_id)
        return self.subject_dir / f"{safe_id}.md"

    def exists(self, subject_id: str) -> bool:
        return self.subject_path(subject_id).exists()

    def load(self, subject_id: str) -> SubjectDocument:
        path = self.subject_path(subject_id)
        if not path.exists():
            raise FileNotFoundError(f"Subject file does not exist: {path}")

        raw = path.read_text(encoding="utf-8")
        parsed = self._split_frontmatter(raw)
        sections = self._split_sections(parsed.body)

        competencies = self._parse_competencies(sections.get("COMPETENCY_MAP", ""))
        quotes = self._parse_quotes(sections.get("QUOTES", ""))
        lesson_model = self._parse_model_list(sections.get("LESSON_MODEL", ""), Lesson)
        worked_examples = self._parse_model_list(sections.get("WORKED_EXAMPLES", ""), WorkedExample)
        retrieval_checks = self._parse_model_list(sections.get("RETRIEVAL_CHECKS", ""), RetrievalCheck)
        misconceptions = self._parse_model_list(sections.get("MISCONCEPTIONS", ""), Misconception)
        transfer_tasks = self._parse_model_list(sections.get("TRANSFER_TASKS", ""), TransferTask)
        lesson_state = self._parse_lesson_state(sections.get("LESSON_STATE", ""))
        srs_data = self._parse_srs(sections.get("SRS_DATA", sections.get("srs_data", "")))
        dependencies_notes = sections.get("DEPENDENCIES", "")
        lessons = sections.get("LESSONS", "")
        notes = self._collect_notes(sections)

        return SubjectDocument(
            subject_id=path.stem,
            frontmatter=SubjectFrontmatter.model_validate(parsed.frontmatter),
            competencies=competencies,
            quotes=quotes,
            lesson_model=lesson_model,
            worked_examples=worked_examples,
            retrieval_checks=retrieval_checks,
            misconceptions=misconceptions,
            transfer_tasks=transfer_tasks,
            lesson_state=lesson_state,
            srs_data=srs_data,
            dependencies_notes=dependencies_notes,
            lessons=lessons,
            notes=notes,
        )

    def save(self, document: SubjectDocument) -> Path:
        path = self.subject_path(document.subject_id)
        rendered = self.render(document)
        path.write_text(rendered, encoding="utf-8")
        return path

    def save_new(self, document: SubjectDocument) -> Path:
        path = self.subject_path(document.subject_id)
        rendered = self.render(document)
        with path.open("x", encoding="utf-8") as handle:
            handle.write(rendered)
        return path

    def render(self, document: SubjectDocument) -> str:
        frontmatter = document.frontmatter.model_dump(exclude_none=False)
        yaml_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()

        parts = [
            "---",
            yaml_text,
            "---",
            "",
            "## COMPETENCY_MAP:",
            self._render_competencies(document.competencies),
            "",
            "## DEPENDENCIES:",
            document.dependencies_notes.strip() or "No cross-level dependencies have been generated yet.",
            "",
            "## QUOTES:",
            self._render_quotes(document.quotes),
            "",
            "## LESSONS:",
            document.lessons.strip() or "Lessons will be generated after source ingestion.",
            "",
            "## LESSON_MODEL:",
            self._render_model_list(document.lesson_model),
            "",
            "## WORKED_EXAMPLES:",
            self._render_model_list(document.worked_examples),
            "",
            "## RETRIEVAL_CHECKS:",
            self._render_model_list(document.retrieval_checks),
            "",
            "## MISCONCEPTIONS:",
            self._render_model_list(document.misconceptions),
            "",
            "## TRANSFER_TASKS:",
            self._render_model_list(document.transfer_tasks),
            "",
            "## LESSON_STATE:",
            self._render_lesson_state(document.lesson_state),
            "",
            "## SRS_DATA:",
            self._render_srs(document.srs_data),
        ]

        if document.notes.strip():
            parts.extend(["", "## NOTES:", document.notes.strip()])

        return "\n".join(parts).rstrip() + "\n"

    def create(self, subject_id: str, frontmatter: SubjectFrontmatter | None = None) -> SubjectDocument:
        document = SubjectDocument(
            subject_id=self._validate_subject_id(subject_id),
            frontmatter=frontmatter or SubjectFrontmatter(),
        )
        self.save(document)
        return document

    def _split_frontmatter(self, raw: str) -> MarkdownSections:
        match = self._frontmatter_re.match(raw)
        if not match:
            return MarkdownSections(frontmatter={}, body=raw)

        frontmatter_text = match.group(1)
        body = raw[match.end() :]
        loaded = yaml.safe_load(frontmatter_text) or {}
        if not isinstance(loaded, dict):
            raise ValueError("Frontmatter must be a YAML object")
        return MarkdownSections(frontmatter=loaded, body=body)

    def _split_sections(self, body: str) -> dict[str, str]:
        matches = list(self._heading_re.finditer(body))
        if not matches:
            return {"NOTES": body.strip()} if body.strip() else {}

        sections: dict[str, str] = {}
        for index, match in enumerate(matches):
            title = self._normalize_heading(match.group(1))
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            sections[title] = body[start:end].strip()
        return sections

    def _parse_competencies(self, text: str) -> list[Competency]:
        rows = self._table_rows(text)
        competencies: list[Competency] = []
        for row in rows:
            if len(row) < 5:
                raise ValueError(f"Invalid competency row: {row}")
            competencies.append(
                Competency(
                    id=row[0],
                    name=row[1],
                    level=int(row[2]),
                    dependencies=self._parse_dependency_cell(row[3]),
                    mastery_percent=self._parse_percent(row[4]),
                )
            )
        return competencies

    def _parse_quotes(self, text: str) -> list[Quote]:
        rows = self._table_rows(text)
        quotes: list[Quote] = []
        for row in rows:
            if len(row) < 4:
                raise ValueError(f"Invalid quote row: {row}")
            quotes.append(
                Quote(
                    text=row[0],
                    source_ref=row[1],
                    competency_id=row[2],
                    level_id=int(row[3]),
                )
            )
        return quotes

    def _parse_srs(self, text: str) -> dict[str, SRSData]:
        text = text.strip()
        if not text:
            return {}

        if text.startswith("```"):
            text = self._strip_fence(text)

        loaded = yaml.safe_load(text)
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            raise ValueError("SRS_DATA must be a YAML or JSON object")

        return {str(key): SRSData.model_validate(value or {}) for key, value in loaded.items()}

    def _parse_model_list(self, text: str, model_type: type[BaseModel]) -> list[Any]:
        loaded = self._parse_yaml_section(text, default=[])
        if loaded is None:
            return []
        if not isinstance(loaded, list):
            raise ValueError(f"{model_type.__name__} section must be a YAML list")
        return [model_type.model_validate(item or {}) for item in loaded]

    def _parse_lesson_state(self, text: str) -> dict[str, LessonState]:
        loaded = self._parse_yaml_section(text, default={})
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            raise ValueError("LESSON_STATE must be a YAML object")
        return {str(key): LessonState.model_validate(value or {}) for key, value in loaded.items()}

    def _parse_yaml_section(self, text: str, default: Any) -> Any:
        text = text.strip()
        if not text:
            return default
        if text.startswith("```"):
            text = self._strip_fence(text)
        return yaml.safe_load(text)

    def _collect_notes(self, sections: dict[str, str]) -> str:
        reserved = {
            "COMPETENCY_MAP",
            "DEPENDENCIES",
            "QUOTES",
            "LESSONS",
            "LESSON_MODEL",
            "WORKED_EXAMPLES",
            "RETRIEVAL_CHECKS",
            "MISCONCEPTIONS",
            "TRANSFER_TASKS",
            "LESSON_STATE",
            "SRS_DATA",
            "srs_data",
        }
        note_parts = []
        for title, content in sections.items():
            if title not in reserved and content:
                note_parts.append(f"## {title}:\n{content}")
        return "\n\n".join(note_parts).strip()

    def _table_rows(self, text: str) -> list[list[str]]:
        rows: list[list[str]] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or not line.startswith("|"):
                continue
            cells = [self._unescape_table_cell(cell.strip()) for cell in self._split_table_cells(line)]
            if self._is_separator_row(cells) or self._is_header_row(cells):
                continue
            rows.append(cells)
        return rows

    def _render_competencies(self, competencies: list[Competency]) -> str:
        lines = [
            "| ID | Name | Level | Dependencies | Mastery % |",
            "| --- | --- | ---: | --- | ---: |",
        ]
        for competency in competencies:
            dependencies = ", ".join(competency.dependencies) if competency.dependencies else "-"
            lines.append(
                f"| {competency.id} | {competency.name} | {competency.level} | "
                f"{dependencies} | {competency.mastery_percent:g}% |"
            )
        return "\n".join(lines)

    def _render_quotes(self, quotes: list[Quote]) -> str:
        lines = [
            "| Verbatim Text | Source Page/Ref | Competency ID | Level ID |",
            "| --- | --- | --- | ---: |",
        ]
        for quote in quotes:
            lines.append(
                f"| {self._escape_table_cell(quote.text)} | {quote.source_ref} | "
                f"{quote.competency_id} | {quote.level_id} |"
            )
        return "\n".join(lines)

    def _render_srs(self, srs_data: dict[str, SRSData]) -> str:
        payload = {key: value.model_dump() for key, value in sorted(srs_data.items())}
        return "```yaml\n" + yaml.safe_dump(payload, sort_keys=False).strip() + "\n```"

    def _render_model_list(self, values: list[BaseModel]) -> str:
        payload = [value.model_dump() for value in values]
        return "```yaml\n" + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).strip() + "\n```"

    def _render_lesson_state(self, lesson_state: dict[str, LessonState]) -> str:
        payload = {key: value.model_dump() for key, value in sorted(lesson_state.items())}
        return "```yaml\n" + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).strip() + "\n```"

    def _strip_fence(self, text: str) -> str:
        lines = text.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
        raise ValueError("Malformed fenced SRS_DATA block")

    def _normalize_heading(self, title: str) -> str:
        return title.strip().rstrip(":")

    def _validate_subject_id(self, subject_id: str) -> str:
        subject_id = subject_id.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", subject_id):
            raise ValueError("subject_id may only contain letters, numbers, underscores, and hyphens")
        return subject_id

    def _parse_dependency_cell(self, value: str) -> list[str]:
        value = value.strip()
        if not value or value in {"-", "none", "None", "[]"}:
            return []
        return [item.strip() for item in value.split(",") if item.strip()]

    def _parse_percent(self, value: str) -> float:
        return float(value.strip().rstrip("%"))

    def _is_separator_row(self, cells: list[str]) -> bool:
        return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)

    def _is_header_row(self, cells: list[str]) -> bool:
        lowered = tuple(cell.lower() for cell in cells)
        return lowered in {
            ("id", "name", "level", "dependencies", "mastery %"),
            ("verbatim text", "source page/ref", "competency id", "level id"),
        }

    def _escape_table_cell(self, value: str) -> str:
        return value.replace("|", "\\|").replace("\n", "<br>")

    def _unescape_table_cell(self, value: str) -> str:
        return value.replace("\\|", "|").replace("<br>", "\n")

    def _split_table_cells(self, line: str) -> list[str]:
        stripped = line.strip()
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]

        cells: list[str] = []
        current: list[str] = []
        escaped = False
        for char in stripped:
            if escaped:
                current.append("\\" + char if char != "|" else char)
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == "|":
                cells.append("".join(current))
                current = []
                continue
            current.append(char)
        if escaped:
            current.append("\\")
        cells.append("".join(current))
        return cells


def json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return json.dumps(value)
