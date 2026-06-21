from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from SourceMind.backend.services.course_models import CourseDocument


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COURSE_DIR = PROJECT_ROOT / "data" / "courses"


class CourseStore:
    """Local Markdown + JSON persistence for SourceMind courses."""

    _frontmatter_re = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
    _json_re = re.compile(r"## COURSE_JSON:\s*```json\s*(.*?)\s*```", re.DOTALL)

    def __init__(self, course_dir: Path | str = DEFAULT_COURSE_DIR) -> None:
        self.course_dir = Path(course_dir)
        self.course_dir.mkdir(parents=True, exist_ok=True)

    def list_course_ids(self) -> list[str]:
        return sorted(path.stem for path in self.course_dir.glob("*.md"))

    def course_path(self, course_id: str) -> Path:
        safe_id = self.validate_id(course_id)
        return self.course_dir / f"{safe_id}.md"

    def exists(self, course_id: str) -> bool:
        return self.course_path(course_id).exists()

    def load(self, course_id: str) -> CourseDocument:
        path = self.course_path(course_id)
        if not path.exists():
            raise FileNotFoundError(f"Course file does not exist: {path}")

        raw = path.read_text(encoding="utf-8")
        match = self._json_re.search(raw)
        if not match:
            raise ValueError(f"Course file is missing COURSE_JSON: {path}")
        payload = json.loads(match.group(1))
        return CourseDocument.model_validate(payload)

    def save(self, course: CourseDocument) -> Path:
        course.updated_at = datetime.now(UTC).isoformat(timespec="seconds")
        path = self.course_path(course.course_id)
        path.write_text(self.render(course), encoding="utf-8")
        return path

    def save_new(self, course: CourseDocument) -> Path:
        course.updated_at = datetime.now(UTC).isoformat(timespec="seconds")
        path = self.course_path(course.course_id)
        with path.open("x", encoding="utf-8") as handle:
            handle.write(self.render(course))
        return path

    def render(self, course: CourseDocument) -> str:
        frontmatter: dict[str, Any] = {
            "schema_version": course.schema_version,
            "course_id": course.course_id,
            "title": course.title,
            "status": course.status.value,
            "created_at": course.created_at,
            "updated_at": course.updated_at,
        }
        frontmatter_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
        json_text = json.dumps(course.model_dump(mode="json"), indent=2, ensure_ascii=False)

        outline_lines = []
        competency_lines = []
        for competency in course.competencies:
            prereqs = ", ".join(competency.prerequisite_ids) if competency.prerequisite_ids else "None"
            lessons = ", ".join(competency.lesson_ids) if competency.lesson_ids else "None"
            competency_lines.append(
                f"- {competency.id}: {competency.title} "
                f"({round(competency.mastery.mastery_percent)}% mastery, level {competency.level}, prerequisites: {prereqs}, lessons: {lessons})"
            )
        for chapter in course.chapters:
            outline_lines.append(f"- {chapter.number} {chapter.title}")
            for section in chapter.sections:
                marker = "complete" if section.completed else section.status.value
                outline_lines.append(f"  - {section.number} {section.title} [{marker}]")

        return (
            f"---\n{frontmatter_text}\n---\n\n"
            f"# {course.title}\n\n"
            "## COMPETENCY_MAP:\n"
            f"{chr(10).join(competency_lines) if competency_lines else '- No competencies generated yet.'}\n\n"
            "## OUTLINE:\n"
            f"{chr(10).join(outline_lines) if outline_lines else '- No outline generated yet.'}\n\n"
            "## COURSE_JSON:\n"
            "```json\n"
            f"{json_text}\n"
            "```\n"
        )

    def unique_id(self, title: str) -> str:
        base = self.slug(title) or "course"
        suffix = 1
        while True:
            candidate = base if suffix == 1 else f"{base}_{suffix}"
            if not self.exists(candidate):
                return candidate
            suffix += 1

    @classmethod
    def slug(cls, value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip().lower()).strip("_")
        return re.sub(r"_+", "_", slug)

    @classmethod
    def validate_id(cls, course_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", course_id):
            raise ValueError(f"Invalid course_id: {course_id}")
        return course_id
