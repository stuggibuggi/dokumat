from __future__ import annotations

import json
from difflib import SequenceMatcher
from uuid import UUID

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.models import Document, DocumentSection, ReviewTemplate
from app.schemas import StructureMappingItemRead, StructureMappingResponse


MAPPING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "template_section_id": {"type": "string"},
                    "matched_document_section_id": {"type": ["string", "null"]},
                    "confidence": {"type": "number"},
                    "reasoning": {"type": "string"},
                },
                "required": ["template_section_id", "matched_document_section_id", "confidence", "reasoning"],
            },
        }
    },
    "required": ["items"],
}


class StructureMapperService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key, timeout=settings.openai_timeout_seconds)

    def map_template_to_document(
        self,
        db: Session,
        template_id: UUID,
        document_id: UUID,
    ) -> StructureMappingResponse:
        template = db.scalar(
            select(ReviewTemplate)
            .options(selectinload(ReviewTemplate.sections))
            .where(ReviewTemplate.id == template_id)
        )
        if template is None:
            raise ValueError("Vorlage nicht gefunden")
        if template.status != "ready":
            raise ValueError("Vorlage ist noch nicht bereit")

        document = db.scalar(
            select(Document)
            .options(selectinload(Document.sections))
            .where(Document.id == document_id)
        )
        if document is None:
            raise ValueError("Dokument nicht gefunden")
        if not document.sections:
            raise ValueError("Dokument enthält noch keine Abschnitte")

        template_payload = [
            {
                "template_section_id": str(section.id),
                "heading": section.heading,
                "level": section.level,
                "requirement_summary": section.requirement_summary[:500],
                "questions": section.questions[:6],
            }
            for section in sorted(template.sections, key=lambda item: item.sort_index)
        ]
        document_payload = [
            {
                "document_section_id": str(section.id),
                "heading": section.heading,
                "level": section.level,
                "summary": (section.summary or "")[:500],
                "excerpt": (section.cleaned_text or section.raw_text_exact or "")[:500],
                "start_page": section.start_page,
                "end_page": section.end_page,
            }
            for section in sorted(document.sections, key=lambda item: item.sort_index)
        ]

        mapped_items = self._map_with_ai(template_payload, document_payload)
        if not mapped_items:
            mapped_items = self._fallback_map(template_payload, document_payload)

        document_index = {str(section.id): section for section in document.sections}
        template_index = {str(section.id): section for section in template.sections}
        items: list[StructureMappingItemRead] = []
        for item in mapped_items:
            template_section = template_index.get(item["template_section_id"])
            if template_section is None:
                continue
            document_section = document_index.get(item.get("matched_document_section_id") or "")
            items.append(
                StructureMappingItemRead(
                    template_section_id=template_section.id,
                    template_heading=template_section.heading,
                    template_level=template_section.level,
                    matched_document_section_id=document_section.id if document_section else None,
                    matched_document_heading=document_section.heading if document_section else None,
                    matched_start_page=document_section.start_page if document_section else None,
                    matched_end_page=document_section.end_page if document_section else None,
                    confidence=float(item["confidence"]),
                    reasoning=item["reasoning"],
                )
            )

        return StructureMappingResponse(template_id=template.id, document_id=document.id, items=items)

    def _map_with_ai(self, template_payload: list[dict], document_payload: list[dict]) -> list[dict]:
        payload = {
            "template_sections": template_payload,
            "document_sections": document_payload,
        }
        try:
            response = self.client.responses.create(
                model=self.settings.openai_model,
                input=[
                    {
                        "role": "system",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "Vergleiche zwei JSON-Strukturen: eine Vorlagenstruktur und die Struktur eines Dokuments. "
                                    "Ordne jedem Vorlagenabschnitt höchstens einen passenden Dokumentabschnitt zu. "
                                    "Ignoriere Nummerierungen und bewerte nur anhand von Überschrift, Anforderungszusammenfassung, "
                                    "Fragen und Abschnittstext. Wähle null, wenn kein sinnvoller Match existiert."
                                ),
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": json.dumps(payload, ensure_ascii=False)}],
                    },
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "structure_mapping",
                        "schema": MAPPING_SCHEMA,
                        "strict": True,
                    }
                },
            )
            parsed = json.loads(response.output_text)
            return parsed.get("items", [])
        except Exception:
            return []

    def _fallback_map(self, template_payload: list[dict], document_payload: list[dict]) -> list[dict]:
        results: list[dict] = []
        for template_item in template_payload:
            best_match: dict | None = None
            best_score = 0.0
            template_text = self._normalize(
                " ".join(
                    [
                        template_item.get("heading", ""),
                        template_item.get("requirement_summary", ""),
                        " ".join(template_item.get("questions", [])),
                    ]
                )
            )
            for document_item in document_payload:
                document_text = self._normalize(
                    " ".join(
                        [
                            document_item.get("heading", ""),
                            document_item.get("summary", ""),
                            document_item.get("excerpt", ""),
                        ]
                    )
                )
                score = SequenceMatcher(None, template_text, document_text).ratio()
                if score > best_score:
                    best_score = score
                    best_match = document_item

            results.append(
                {
                    "template_section_id": template_item["template_section_id"],
                    "matched_document_section_id": best_match["document_section_id"] if best_match and best_score >= 0.45 else None,
                    "confidence": best_score if best_match else 0.0,
                    "reasoning": "Fallback-Zuordnung auf Basis der textuellen Ähnlichkeit von Struktur-JSON und Abschnittstext.",
                }
            )
        return results

    def _normalize(self, text: str) -> str:
        return " ".join(
            "".join(character if character.isalnum() or character.isspace() else " " for character in text.casefold()).split()
        )
