from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re

from app.config import Settings
from app.services.pdf_extractor import ExtractedPage, HeadingCandidate
from app.services.template_sections import TemplateSection


@dataclass(slots=True)
class RawSection:
    title: str
    level: int
    start_page: int
    end_page: int
    sort_index: int
    text_parts: list[str] = field(default_factory=list)
    page_numbers: list[int] = field(default_factory=list)
    image_keys: list[str] = field(default_factory=list)

    @property
    def raw_text(self) -> str:
        return "\n".join(part for part in self.text_parts if part).strip()

    @property
    def raw_text_exact(self) -> str:
        return self.raw_text

    @property
    def cleaned_text(self) -> str:
        cleaned_lines: list[str] = []
        previous_blank = False

        for part in self.text_parts:
            line = self._normalize_inline_spacing(part)
            if not line:
                if not previous_blank and cleaned_lines:
                    cleaned_lines.append("")
                previous_blank = True
                continue
            cleaned_lines.append(line)
            previous_blank = False

        return "\n".join(cleaned_lines).strip()

    @property
    def markdown_text(self) -> str:
        body_lines = [line for line in self.cleaned_text.splitlines()]
        markdown_lines = [f"# {self.title}", ""]

        for line in body_lines:
            if not line:
                if markdown_lines[-1] != "":
                    markdown_lines.append("")
                continue

            if self._looks_like_list_item(line):
                markdown_lines.append(f"- {line.lstrip('-•* ').strip()}")
            else:
                markdown_lines.append(line)

        return "\n".join(markdown_lines).strip()

    def _normalize_inline_spacing(self, value: str) -> str:
        collapsed = re.sub(r"[ \t]+", " ", value.replace("\u00a0", " ")).strip()
        collapsed = re.sub(r"\s+([,.;:!?])", r"\1", collapsed)
        collapsed = re.sub(r"([(/])\s+", r"\1", collapsed)
        collapsed = re.sub(r"\s+([/)])", r"\1", collapsed)
        return collapsed

    def _looks_like_list_item(self, value: str) -> bool:
        stripped = value.strip()
        if stripped.startswith(("- ", "• ", "* ")):
            return True
        return bool(re.match(r"^\d+[.)]\s+", stripped))


class SectionBuilder:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build(self, pages: list[ExtractedPage], template_sections: list[TemplateSection] | None = None) -> list[RawSection]:
        heading_count = sum(len(page.headings) for page in pages)
        if heading_count == 0:
            return self._fallback_sections(pages)

        matched_headings = self._match_template_headings(pages, template_sections or [])
        sections: list[RawSection] = []
        current = RawSection(title="Dokumentanfang", level=1, start_page=1, end_page=1, sort_index=1)

        for page in pages:
            heading_map = (
                matched_headings.get(page.page_number, {})
                if matched_headings
                else {candidate.line_index: candidate for candidate in self._valid_content_headings(page.headings)}
            )
            line_index = 0

            while line_index < len(page.lines):
                heading = heading_map.get(line_index)
                if heading:
                    if current.raw_text:
                        current.end_page = page.page_number
                        sections.append(current)
                        current = self._start_new_section(len(sections) + 1, page.page_number, heading)
                    else:
                        current.title = heading.text
                        current.level = heading.level
                        current.start_page = page.page_number
                        current.end_page = page.page_number
                    line_index += 1
                    continue

                line = page.lines[line_index]
                current.text_parts.append(line.text)
                if page.page_number not in current.page_numbers:
                    current.page_numbers.append(page.page_number)
                line_index += 1

            current.end_page = page.page_number
            current.image_keys.extend(image.image_id for image in page.images)

        if current.raw_text:
            sections.append(current)

        cleaned_sections = [section for section in sections if section.raw_text]
        if not cleaned_sections:
            return self._fallback_sections(pages)

        if len(cleaned_sections) == 1 and cleaned_sections[0].title == "Dokumentanfang":
            return self._fallback_sections(pages)

        return cleaned_sections

    def _valid_headings(self, headings: list[HeadingCandidate]) -> list[HeadingCandidate]:
        return [heading for heading in headings if heading.confidence >= 0.6]

    def _valid_content_headings(self, headings: list[HeadingCandidate]) -> list[HeadingCandidate]:
        return [heading for heading in self._valid_headings(headings) if not self._looks_like_toc_entry(heading.text)]

    def _match_template_headings(
        self, pages: list[ExtractedPage], template_sections: list[TemplateSection]
    ) -> dict[int, dict[int, HeadingCandidate]]:
        if not template_sections:
            return {}

        title_to_indices: dict[str, list[int]] = {}
        for index, template in enumerate(template_sections):
            title_to_indices.setdefault(template.normalized_title, []).append(index)

        matches: list[tuple[int, int, HeadingCandidate]] = []
        last_template_index = -1
        main_started = False

        for page in pages:
            for heading in self._valid_headings(page.headings):
                normalized = self._normalize_heading_text(heading.text)
                if not normalized or self._looks_like_toc_entry(heading.text):
                    continue
                if normalized == 'anwendungsdokumentation':
                    main_started = True
                if not main_started:
                    continue
                candidate_indices = title_to_indices.get(normalized, [])
                selected_index = next((idx for idx in candidate_indices if idx > last_template_index), None)
                if selected_index is None:
                    selected_index = self._fuzzy_template_index(normalized, template_sections, last_template_index)
                if selected_index is None:
                    continue
                matches.append((page.page_number, selected_index, heading))
                last_template_index = selected_index

        if len(matches) < min(8, max(3, len(template_sections) // 10)):
            return {}

        matched_headings: dict[int, dict[int, HeadingCandidate]] = {}
        for page_number, _, heading in matches:
            matched_headings.setdefault(page_number, {})[heading.line_index] = heading
        return matched_headings


    def _fuzzy_template_index(
        self, normalized_heading: str, template_sections: list[TemplateSection], last_template_index: int
    ) -> int | None:
        best_index: int | None = None
        best_score = 0.0
        for index, template in enumerate(template_sections):
            if index <= last_template_index:
                continue
            score = SequenceMatcher(None, normalized_heading, template.normalized_title).ratio()
            if normalized_heading in template.normalized_title or template.normalized_title in normalized_heading:
                score = max(score, 0.9)
            if score > best_score:
                best_score = score
                best_index = index
        return best_index if best_score >= 0.72 else None

    def _start_new_section(self, sort_index: int, page_number: int, heading: HeadingCandidate) -> RawSection:
        return RawSection(
            title=heading.text,
            level=heading.level,
            start_page=page_number,
            end_page=page_number,
            sort_index=sort_index,
            page_numbers=[page_number],
        )

    def _fallback_sections(self, pages: list[ExtractedPage]) -> list[RawSection]:
        sections: list[RawSection] = []
        page_window = self.settings.pages_per_fallback_section

        for start_index in range(0, len(pages), page_window):
            batch = pages[start_index : start_index + page_window]
            first_page = batch[0].page_number
            last_page = batch[-1].page_number
            section = RawSection(
                title=f"Seiten {first_page}-{last_page}",
                level=1,
                start_page=first_page,
                end_page=last_page,
                sort_index=len(sections) + 1,
                page_numbers=[page.page_number for page in batch],
            )
            for page in batch:
                section.text_parts.append(page.text)
                section.image_keys.extend(image.image_id for image in page.images)
            sections.append(section)

        return sections

    def _normalize_heading_text(self, value: str) -> str:
        cleaned = re.sub(r'^(\d+(?:\.\d+)*)\s+', '', value.strip())
        cleaned = re.sub(r'\(.*?\)', '', cleaned)
        cleaned = re.sub(r'[^\w\s]+', ' ', cleaned.casefold())
        return re.sub(r'\s+', ' ', cleaned).strip()

    def _looks_like_toc_entry(self, value: str) -> bool:
        normalized = self._normalize_heading_text(value)
        if normalized in {"table of contents", "contents", "inhaltsverzeichnis"}:
            return True
        if normalized.startswith(("table of contents ", "contents ", "inhaltsverzeichnis ")):
            return True
        return bool(re.search(r'\.{4,}|\s+\d+$', value))
