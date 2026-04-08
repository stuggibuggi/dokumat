from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import fitz

from app.config import Settings


HEADING_NUMBERING_RE = re.compile(r"^(\d+(?:\.\d+)*)\s+\S+")
DATE_PREFIX_RE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{2,4}(?:\s+|$)")


@dataclass(slots=True)
class ExtractedLine:
    index: int
    text: str
    font_size: float
    is_bold: bool


@dataclass(slots=True)
class HeadingCandidate:
    line_index: int
    text: str
    font_size: float
    level: int
    confidence: float


@dataclass(slots=True)
class ExtractedImage:
    image_id: str
    page_number: int
    sort_index: int
    filename: str
    relative_path: str
    mime_type: str | None
    width: int | None
    height: int | None
    sha256: str


@dataclass(slots=True)
class ExtractedPage:
    page_number: int
    text: str
    lines: list[ExtractedLine]
    headings: list[HeadingCandidate]
    images: list[ExtractedImage]


class PDFExtractor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def extract(self, pdf_path: Path, image_dir: Path) -> list[ExtractedPage]:
        document = fitz.open(pdf_path)
        pages: list[ExtractedPage] = []

        for page_index in range(document.page_count):
            page = document.load_page(page_index)
            lines = self._extract_lines(page)
            max_font_size = max((line.font_size for line in lines), default=self.settings.heading_min_font_size)
            headings = self._detect_headings(lines, max_font_size)
            images = self._extract_images(document, page, image_dir)
            page_text = "\n".join(line.text for line in lines)
            pages.append(
                ExtractedPage(
                    page_number=page_index + 1,
                    text=page_text,
                    lines=lines,
                    headings=headings,
                    images=images,
                )
            )

        document.close()
        return pages

    def _extract_lines(self, page: fitz.Page) -> list[ExtractedLine]:
        text_dict = page.get_text("dict", sort=True)
        lines: list[ExtractedLine] = []

        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                text = "".join(span.get("text", "") for span in spans).strip()
                if not text:
                    continue
                font_size = max((float(span.get("size", 0.0)) for span in spans), default=0.0)
                is_bold = any("bold" in str(span.get("font", "")).lower() for span in spans)
                lines.append(
                    ExtractedLine(
                        index=len(lines),
                        text=text,
                        font_size=font_size,
                        is_bold=is_bold,
                    )
                )

        return lines

    def _detect_headings(self, lines: list[ExtractedLine], max_font_size: float) -> list[HeadingCandidate]:
        candidates: list[HeadingCandidate] = []
        size_threshold = max(self.settings.heading_min_font_size, max_font_size * self.settings.heading_font_ratio)

        for line in lines:
            text = line.text.strip()
            if len(text) < 3 or len(text) > 180:
                continue
            if self._looks_like_noise_heading(text):
                continue

            uppercase_ratio = self._uppercase_ratio(text)
            has_numbering = bool(HEADING_NUMBERING_RE.match(text))
            has_large_font = line.font_size >= size_threshold
            has_medium_font = line.font_size >= self.settings.heading_min_font_size
            looks_like_heading = any(
                [
                    has_large_font,
                    has_numbering and has_medium_font,
                    line.is_bold and has_medium_font and len(text) < 110,
                    uppercase_ratio > 0.75 and has_medium_font and len(text.split()) <= 12,
                ]
            )

            if not looks_like_heading:
                continue

            confidence = 0.45
            if has_large_font:
                confidence += 0.25
            if line.is_bold:
                confidence += 0.15
            if has_numbering and has_medium_font:
                confidence += 0.15
            if uppercase_ratio > 0.75:
                confidence += 0.05

            level = self._heading_level(line.font_size, max_font_size, has_numbering)
            candidates.append(
                HeadingCandidate(
                    line_index=line.index,
                    text=text,
                    font_size=line.font_size,
                    level=level,
                    confidence=min(confidence, 0.98),
                )
            )

        return candidates

    def _extract_images(self, document: fitz.Document, page: fitz.Page, image_dir: Path) -> list[ExtractedImage]:
        extracted: list[ExtractedImage] = []
        seen_xrefs: set[int] = set()

        for image_index, image_info in enumerate(page.get_images(full=True), start=1):
            xref = int(image_info[0])
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            base_image = document.extract_image(xref)
            image_bytes = base_image.get("image")
            if not image_bytes:
                continue
            image_extension = str(base_image.get("ext", "bin"))
            filename = f"page-{page.number + 1:05d}-{image_index:03d}.{image_extension}"
            image_path = image_dir / filename
            image_path.write_bytes(image_bytes)
            sha256 = hashlib.sha256(image_bytes).hexdigest()
            extracted.append(
                ExtractedImage(
                    image_id=f"p{page.number + 1}-i{image_index}",
                    page_number=page.number + 1,
                    sort_index=image_index,
                    filename=filename,
                    relative_path=image_path.relative_to(self.settings.base_dir).as_posix(),
                    mime_type=f"image/{image_extension}",
                    width=base_image.get("width"),
                    height=base_image.get("height"),
                    sha256=sha256,
                )
            )

        return extracted

    def _heading_level(self, font_size: float, max_font_size: float, has_numbering: bool) -> int:
        if font_size >= max_font_size * 0.98:
            return 1
        if font_size >= max_font_size * 0.92:
            return 2
        if has_numbering:
            return 3
        return 2

    def _uppercase_ratio(self, value: str) -> float:
        letters = [character for character in value if character.isalpha()]
        if not letters:
            return 0.0
        uppercase = [character for character in letters if character.isupper()]
        return len(uppercase) / len(letters)

    def _looks_like_noise_heading(self, value: str) -> bool:
        stripped = value.strip()
        if DATE_PREFIX_RE.match(stripped):
            return True
        if stripped.lower().endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".xml")):
            return True
        if re.fullmatch(r"[\W_]+", stripped):
            return True
        if len(stripped.split()) <= 3 and any(char in stripped for char in ("_", ".csv", ".xml", ".xlsx", ".xls")):
            return True
        if sum(character.isalpha() for character in stripped) < 3:
            return True
        return False
