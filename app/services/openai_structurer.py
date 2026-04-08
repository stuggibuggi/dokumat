from __future__ import annotations

import json

from openai import OpenAI

from app.config import Settings
from app.services.section_builder import RawSection


SECTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "normalized_heading": {"type": "string"},
        "summary": {"type": "string"},
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 12,
        },
        "confidence": {"type": "number"},
    },
    "required": ["normalized_heading", "summary", "keywords", "confidence"],
}


class OpenAISectionStructurer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key, timeout=settings.openai_timeout_seconds)

    def enrich(self, section: RawSection) -> dict:
        return self.enrich_existing(
            heading=section.title,
            start_page=section.start_page,
            end_page=section.end_page,
            raw_text=section.raw_text,
            image_count=len(section.image_keys),
            sort_index=section.sort_index,
        )

    def enrich_existing(
        self,
        *,
        heading: str,
        start_page: int,
        end_page: int,
        raw_text: str,
        image_count: int,
        sort_index: int = 0,
    ) -> dict:
        excerpt = raw_text[: self.settings.section_excerpt_chars]
        payload = {
            "heading": heading,
            "pages": {"start": start_page, "end": end_page},
            "image_count": image_count,
            "excerpt": excerpt,
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
                                    "Du strukturierst PDF-Abschnitte für eine PostgreSQL-Datenbank. "
                                    "Normalisiere die Überschrift, fasse den Abschnitt präzise zusammen, "
                                    "liefere sinnvolle Schlagwörter und erfinde keine Inhalte."
                                ),
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": json.dumps(payload, ensure_ascii=False),
                            }
                        ],
                    },
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "document_section",
                        "schema": SECTION_SCHEMA,
                        "strict": True,
                    }
                },
            )
            return json.loads(response.output_text)
        except Exception:
            normalized_heading = heading if heading != "Dokumentanfang" else f"Abschnitt {sort_index or 1}"
            summary = raw_text[:500].strip()
            return {
                "normalized_heading": normalized_heading,
                "summary": summary,
                "keywords": [],
                "confidence": 0.35,
            }

    def embed_text(self, text: str) -> list[float] | None:
        content = text.strip()
        if not content:
            return None

        try:
            response = self.client.embeddings.create(
                model=self.settings.openai_embedding_model,
                input=content[:8000],
                dimensions=self.settings.embedding_dimensions,
            )
            return list(response.data[0].embedding)
        except Exception:
            return None
