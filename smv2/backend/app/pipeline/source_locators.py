from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol


class SourceLocator(Protocol):
    type: str
    asset_id: str | None

    def to_dict(self) -> dict[str, Any]: ...

    def export_label(self) -> str: ...


@dataclass(frozen=True)
class PdfPageLocator:
    asset_id: str
    page_start: int
    page_end: int
    type: Literal["pdf_pages"] = "pdf_pages"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "asset_id": self.asset_id,
            "page_start": self.page_start + 1,
            "page_end": self.page_end + 1,
        }

    def export_label(self) -> str:
        if self.page_start == self.page_end:
            return f"PDF page {self.page_start + 1}"
        return f"PDF pages {self.page_start + 1}-{self.page_end + 1}"


@dataclass(frozen=True)
class HeadingLocator:
    asset_id: str | None
    heading_path: list[str]
    type: Literal["heading"] = "heading"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "asset_id": self.asset_id,
            "heading_path": list(self.heading_path),
        }

    def export_label(self) -> str:
        return " > ".join(self.heading_path)


@dataclass(frozen=True)
class SlideRangeLocator:
    asset_id: str | None
    slide_start: int
    slide_end: int
    type: Literal["slide_range"] = "slide_range"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "asset_id": self.asset_id,
            "slide_start": self.slide_start,
            "slide_end": self.slide_end,
        }

    def export_label(self) -> str:
        if self.slide_start == self.slide_end:
            return f"Slide {self.slide_start}"
        return f"Slides {self.slide_start}-{self.slide_end}"


@dataclass(frozen=True)
class ChapterFragmentLocator:
    asset_id: str | None
    chapter_label: str
    fragment_id: str | None = None
    type: Literal["chapter_fragment"] = "chapter_fragment"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": self.type,
            "asset_id": self.asset_id,
            "chapter_label": self.chapter_label,
        }
        if self.fragment_id is not None:
            payload["fragment_id"] = self.fragment_id
        return payload

    def export_label(self) -> str:
        if self.fragment_id:
            return f"{self.chapter_label}#{self.fragment_id}"
        return self.chapter_label


@dataclass(frozen=True)
class CompositeLocator:
    asset_id: str
    locators: tuple[LocatorValue, ...]
    type: Literal["composite"] = "composite"

    @classmethod
    def from_locators(cls, locators: list[LocatorValue]) -> CompositeLocator:
        flattened: list[LocatorValue] = []
        for locator in locators:
            if isinstance(locator, CompositeLocator):
                flattened.extend(locator.locators)
            else:
                flattened.append(locator)
        if not flattened:
            raise ValueError("composite locator requires at least one locator")

        asset_ids = {locator.asset_id for locator in flattened}
        if None in asset_ids or len(asset_ids) != 1:
            raise ValueError("composite locator requires locators from one non-null asset")

        return cls(asset_id=str(next(iter(asset_ids))), locators=tuple(flattened))

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "asset_id": self.asset_id,
            "locators": [locator.to_dict() for locator in self.locators],
        }

    def export_label(self) -> str:
        return " + ".join(locator.export_label() for locator in self.locators)


LocatorValue = PdfPageLocator | HeadingLocator | SlideRangeLocator | ChapterFragmentLocator | CompositeLocator


def locator_from_dict(payload: dict[str, Any] | None) -> LocatorValue | None:
    if payload is None:
        return None
    locator_type = payload.get("type")
    if locator_type == "pdf_pages":
        return PdfPageLocator(
            asset_id=str(payload["asset_id"]),
            page_start=int(payload["page_start"]) - 1,
            page_end=int(payload["page_end"]) - 1,
        )
    if locator_type == "heading":
        return HeadingLocator(
            asset_id=payload.get("asset_id"),
            heading_path=[str(part) for part in payload.get("heading_path", [])],
        )
    if locator_type == "slide_range":
        return SlideRangeLocator(
            asset_id=payload.get("asset_id"),
            slide_start=int(payload["slide_start"]),
            slide_end=int(payload["slide_end"]),
        )
    if locator_type == "chapter_fragment":
        return ChapterFragmentLocator(
            asset_id=payload.get("asset_id"),
            chapter_label=str(payload["chapter_label"]),
            fragment_id=payload.get("fragment_id"),
        )
    if locator_type == "composite":
        child_locators: list[LocatorValue] = []
        for child in payload.get("locators", []):
            child_locator = locator_from_dict(child)
            if child_locator is None:
                raise ValueError("composite locator child cannot be null")
            child_locators.append(child_locator)
        locator = CompositeLocator.from_locators(child_locators)
        if payload.get("asset_id") is not None and payload.get("asset_id") != locator.asset_id:
            raise ValueError("composite locator asset_id does not match child locators")
        return locator
    raise ValueError(f"unknown source locator type: {locator_type!r}")


def locator_export_label(payload: dict[str, Any] | None) -> str | None:
    locator = locator_from_dict(payload)
    return locator.export_label() if locator is not None else None
