from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

from app.config import Settings
from app.services.pdf_extractor import ExtractedPage, HeadingCandidate, PDFExtractor


DOT_LEADER_RE = re.compile(r'\.{4,}')
NUMBERED_HEADING_RE = re.compile(r'^(?P<number>\d+(?:\.\d+)*)\s+(?P<title>.+?)$')
TRAILING_PAGE_RE = re.compile(r'\s+\d+$')


@dataclass(slots=True)
class TemplateSection:
    key: str
    title: str
    level: int
    full_heading: str
    normalized_title: str


class TemplateSectionProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.extractor = PDFExtractor(settings)
        self._cache: list[TemplateSection] | None = None
        self._cache_name: str | None = None

    def load(self) -> list[TemplateSection]:
        template_path = self._find_template_pdf()
        if template_path is None:
            return []
        if self._cache is not None and self._cache_name == template_path.name:
            return self._cache

        image_dir = self.settings.images_dir / '_template_sections'
        image_dir.mkdir(parents=True, exist_ok=True)
        pages = self.extractor.extract(template_path, image_dir)
        sections = self._extract_sections(pages)
        self._cache = sections
        self._cache_name = template_path.name
        return sections

    def _find_template_pdf(self) -> Path | None:
        candidates = sorted(self.settings.base_dir.glob('AWD - ICTOxxxx*.pdf'))
        return candidates[0] if candidates else None

    def _extract_sections(self, pages: list[ExtractedPage]) -> list[TemplateSection]:
        sections: list[TemplateSection] = []
        seen: set[str] = set()
        in_main_content = False

        for page in pages:
            for heading in page.headings:
                parsed = self._parse_heading(heading)
                if parsed is None:
                    continue
                number, title = parsed
                if self._normalize_title(title).startswith('anwendungsdokumentation'):
                    in_main_content = True
                if not in_main_content:
                    continue
                key = f'{number}|{self._normalize_title(title)}'
                if key in seen:
                    continue
                seen.add(key)
                sections.append(
                    TemplateSection(
                        key=number,
                        title=title,
                        level=number.count('.') + 1,
                        full_heading=f'{number} {title}',
                        normalized_title=self._normalize_title(title),
                    )
                )
        return sections

    def _parse_heading(self, heading: HeadingCandidate) -> tuple[str, str] | None:
        text = heading.text.strip()
        if DOT_LEADER_RE.search(text):
            return None
        text = TRAILING_PAGE_RE.sub('', text).strip()
        match = NUMBERED_HEADING_RE.match(text)
        if not match:
            return None
        number = match.group('number')
        title = match.group('title').strip()
        if len(number.split('.')) > 5:
            return None
        if not title:
            return None
        return number, title

    def _normalize_title(self, title: str) -> str:
        value = title.casefold()
        value = re.sub(r'\(.*?\)', '', value)
        value = re.sub(r'[^\w\s]+', ' ', value)
        value = re.sub(r'\s+', ' ', value).strip()
        return value
