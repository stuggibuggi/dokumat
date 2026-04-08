from __future__ import annotations

import re

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.db import is_pgvector_enabled
from app.models import Document, DocumentSection
from app.schemas import SectionSearchRequest, SectionSearchResponse, SectionSearchResult
from app.services.openai_structurer import OpenAISectionStructurer


class SemanticSearchService:
    def __init__(self, structurer: OpenAISectionStructurer) -> None:
        self.structurer = structurer

    def search_sections(self, db: Session, payload: SectionSearchRequest) -> SectionSearchResponse:
        search_text = func.concat_ws(
            " ",
            DocumentSection.normalized_heading,
            func.coalesce(DocumentSection.summary, ""),
            DocumentSection.cleaned_text,
        )
        ts_query = func.websearch_to_tsquery("simple", payload.query)
        text_vector = func.to_tsvector("simple", search_text)
        text_rank = func.ts_rank_cd(text_vector, ts_query)
        text_match = text_vector.op("@@")(ts_query)

        query_embedding = self.structurer.embed_text(payload.query) if is_pgvector_enabled() else None
        semantic_score = None
        filters = [text_match]

        if query_embedding:
            semantic_score = case(
                (DocumentSection.embedding.is_not(None), 1 - DocumentSection.embedding.cosine_distance(query_embedding)),
                else_=0.0,
            )
            filters.append(DocumentSection.embedding.is_not(None))

        hybrid_score = (
            semantic_score * 0.7 + func.least(text_rank, 1.0) * 0.3
            if semantic_score is not None
            else text_rank
        )

        statement = (
            select(DocumentSection, Document, hybrid_score.label("hybrid_score"))
            .join(Document, Document.id == DocumentSection.document_id)
            .where(or_(*filters))
            .order_by(hybrid_score.desc())
            .limit(max(1, min(payload.limit, 50)))
        )

        if payload.document_id is not None:
            statement = statement.where(DocumentSection.document_id == payload.document_id)

        rows = db.execute(statement).all()
        results = [
            SectionSearchResult(
                section_id=section.id,
                document_id=document.id,
                document_filename=document.original_filename,
                heading=section.heading,
                normalized_heading=section.normalized_heading,
                summary=section.summary,
                snippet=self._build_snippet(section.cleaned_text or section.raw_text_exact or section.summary or "", payload.query),
                start_page=section.start_page,
                end_page=section.end_page,
                score=max(0.0, float(score_value)),
            )
            for section, document, score_value in rows
        ]
        return SectionSearchResponse(query=payload.query, results=results)

    def _build_snippet(self, text: str, query: str, snippet_length: int = 360) -> str:
        source = " ".join((text or "").split())
        if not source:
            return ""

        terms = [term for term in re.split(r"\W+", query) if len(term) >= 3]
        if not terms:
            return source[:snippet_length]

        lower_source = source.lower()
        first_index = -1
        match_length = 0
        for term in terms:
            index = lower_source.find(term.lower())
            if index != -1 and (first_index == -1 or index < first_index):
                first_index = index
                match_length = len(term)

        if first_index == -1:
            return source[:snippet_length]

        start = max(0, first_index - snippet_length // 3)
        end = min(len(source), start + snippet_length)
        snippet = source[start:end]
        if start > 0:
            snippet = f"…{snippet}"
        if end < len(source):
            snippet = f"{snippet}…"
        return snippet
