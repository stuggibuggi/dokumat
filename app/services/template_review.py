from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path
from uuid import UUID, uuid4

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.db import SessionLocal
from app.models import Document, DocumentSection, ReviewTemplate, ReviewTemplateSection, TemplateCheck, TemplateSectionCheck
from app.schemas import TemplateCheckRead, TemplateSectionMatchRead
from app.services.pdf_extractor import PDFExtractor
from app.services.section_builder import RawSection, SectionBuilder
from app.services.storage import StorageService


TEMPLATE_SECTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "requirement_summary": {"type": "string"},
        "questions": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 12,
        },
    },
    "required": ["requirement_summary", "questions"],
}

SECTION_CHECK_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "coverage_status": {"type": "string", "enum": ["complete", "partial", "missing"]},
        "reasoning": {"type": "string"},
        "missing_topics": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 10,
        },
        "answered_questions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "question": {"type": "string"},
                    "status": {"type": "string", "enum": ["answered", "partial", "missing"]},
                    "evidence": {"type": "string"},
                },
                "required": ["question", "status", "evidence"],
            },
            "maxItems": 20,
        },
        "confidence": {"type": "number"},
    },
    "required": ["coverage_status", "reasoning", "missing_topics", "answered_questions", "confidence"],
}


class JobCancelledError(Exception):
    pass


class TemplateReviewService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.storage = StorageService(settings)
        self.extractor = PDFExtractor(settings)
        self.section_builder = SectionBuilder(settings)
        self.client = OpenAI(api_key=settings.openai_api_key, timeout=settings.openai_timeout_seconds)

    def queue_template_upload(self, db: Session, filename: str, file_bytes: bytes) -> ReviewTemplate:
        template = ReviewTemplate(
            id=uuid4(),
            original_filename=filename,
            display_name=Path(filename).stem,
            storage_path="",
            status="processing",
            section_count=0,
        )
        db.add(template)
        db.flush()

        template_dir = self.settings.templates_dir / str(template.id)
        template_dir.mkdir(parents=True, exist_ok=True)
        target = template_dir / Path(filename).name
        target.write_bytes(file_bytes)
        template.storage_path = self.storage.to_relative(target)
        db.add(template)
        db.commit()
        db.refresh(template)
        return self.get_template(db, template.id)

    def process_template(self, template_id: UUID) -> None:
        with SessionLocal() as db:
            template = self.get_template(db, template_id)
            if template is None:
                return

            try:
                if template.extra_metadata.get("cancel_requested"):
                    self._mark_template_cancelled(db, template)
                    return
                template.status = "processing"
                template.extra_metadata = {**template.extra_metadata, "error_message": None, "cancel_requested": False}
                db.add(template)
                db.commit()

                target = self.storage.to_absolute(template.storage_path)
                image_dir = self.settings.images_dir / f"_template_{template.id}"
                image_dir.mkdir(parents=True, exist_ok=True)
                pages = self.extractor.extract(target, image_dir)
                raw_sections = self.section_builder.build(pages)

                template.sections.clear()
                db.flush()

                for index, section in enumerate(raw_sections, start=1):
                    self._check_template_cancelled(db, template)
                    extracted = self._extract_template_requirements(section)
                    template.sections.append(
                        ReviewTemplateSection(
                            sort_index=index,
                            key=self._section_key(section.title),
                            heading=section.title,
                            normalized_heading=self._normalize(section.title),
                            level=section.level,
                            requirement_summary=extracted["requirement_summary"],
                            questions=extracted["questions"],
                            source_text=section.cleaned_text[:16000],
                            extra_metadata={
                                "start_page": section.start_page,
                                "end_page": section.end_page,
                            },
                        )
                    )

                template.section_count = len(template.sections)
                template.status = "ready"
                template.extra_metadata = {**template.extra_metadata, "error_message": None, "cancel_requested": False}
                db.add(template)
                db.commit()
            except JobCancelledError:
                db.rollback()
                template = self.get_template(db, template_id)
                if template is not None:
                    self._mark_template_cancelled(db, template)
            except Exception as exc:
                template.status = "failed"
                template.extra_metadata = {**template.extra_metadata, "error_message": str(exc), "cancel_requested": False}
                db.add(template)
                db.commit()

    def list_templates(self, db: Session) -> list[ReviewTemplate]:
        query = select(ReviewTemplate).order_by(ReviewTemplate.created_at.desc())
        return list(db.scalars(query).all())

    def get_template(self, db: Session, template_id: UUID) -> ReviewTemplate | None:
        query = (
            select(ReviewTemplate)
            .options(selectinload(ReviewTemplate.sections))
            .where(ReviewTemplate.id == template_id)
        )
        return db.scalar(query)

    def run_check(
        self,
        db: Session,
        template_id: UUID,
        document_id: UUID,
        *,
        section_limit: int | None = None,
        template_section_ids: list[UUID] | None = None,
    ) -> TemplateCheck:
        template, document = self._load_template_and_document(db, template_id, document_id)
        selected_template_sections = self._select_template_sections(
            template,
            section_limit=section_limit,
            template_section_ids=template_section_ids,
        )
        check = TemplateCheck(
            template_id=template.id,
            document_id=document.id,
            status="completed",
            required_section_count=len(selected_template_sections),
            matched_section_count=0,
        )
        db.add(check)
        db.flush()

        matched_count = 0
        persisted_checks: list[TemplateSectionCheck] = []
        for template_section in selected_template_sections:
            document_section, score = self._match_document_section(template_section, document.sections)
            if document_section is None:
                persisted_checks.append(
                    TemplateSectionCheck(
                        template_check_id=check.id,
                        template_section_id=template_section.id,
                        sort_index=template_section.sort_index,
                        template_heading=template_section.heading,
                        document_heading=None,
                        is_present=False,
                        coverage_status="missing",
                        confidence=0.0,
                        reasoning="Kein passender Abschnitt im Dokument gefunden.",
                        missing_topics=template_section.questions or ([template_section.requirement_summary] if template_section.requirement_summary else []),
                        answered_questions=[
                            {"question": question, "status": "missing", "evidence": ""}
                            for question in template_section.questions
                        ],
                    )
                )
                continue

            matched_count += 1
            evaluation = self._evaluate_section(template_section, document_section, score)
            persisted_checks.append(
                TemplateSectionCheck(
                    template_check_id=check.id,
                    template_section_id=template_section.id,
                    document_section_id=document_section.id,
                    sort_index=template_section.sort_index,
                    template_heading=template_section.heading,
                    document_heading=document_section.heading,
                    is_present=True,
                    coverage_status=evaluation["coverage_status"],
                    confidence=float(evaluation["confidence"]),
                    reasoning=evaluation["reasoning"],
                    missing_topics=evaluation["missing_topics"],
                    answered_questions=evaluation["answered_questions"],
                    extra_metadata={"match_score": score},
                )
            )

        check.matched_section_count = matched_count
        completion_ratio = (matched_count / len(selected_template_sections)) if selected_template_sections else 0.0
        check.summary = f"{matched_count} von {len(selected_template_sections)} Vorlagenabschnitten wurden im Dokument gefunden."
        check.extra_metadata = {
            "completion_ratio": completion_ratio,
            "section_limit": section_limit,
            "is_test_run": section_limit is not None,
        }
        check.section_checks = persisted_checks
        db.add(check)
        db.flush()

        payload = self._serialize_check(check, template, document)
        result_path = self.storage.create_template_check_json_target(template.display_name, document.original_filename)
        result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        check.result_storage_path = self.storage.to_relative(result_path)

        db.add(check)
        db.commit()
        db.refresh(check)
        return self.get_check(db, check.id)

    def preview_matches(self, db: Session, template_id: UUID, document_id: UUID) -> list[TemplateSectionMatchRead]:
        template, document = self._load_template_and_document(db, template_id, document_id)
        results: list[TemplateSectionMatchRead] = []
        for template_section in sorted(template.sections, key=lambda item: item.sort_index):
            document_section, score = self._match_document_section(template_section, document.sections)
            results.append(
                TemplateSectionMatchRead(
                    template_section_id=template_section.id,
                    template_heading=template_section.heading,
                    template_level=template_section.level,
                    matched_document_section_id=document_section.id if document_section else None,
                    matched_document_heading=document_section.heading if document_section else None,
                    matched_start_page=document_section.start_page if document_section else None,
                    matched_end_page=document_section.end_page if document_section else None,
                    match_score=score,
                    is_match=document_section is not None,
                )
            )
        return results

    def cancel_template_job(self, db: Session, template_id: UUID) -> ReviewTemplate:
        template = self.get_template(db, template_id)
        if template is None:
            raise ValueError("Vorlage nicht gefunden")
        if template.status in {"ready", "failed", "cancelled"}:
            raise ValueError("Vorlage wird aktuell nicht verarbeitet")

        template.status = "cancelling" if template.status == "processing" else "cancelled"
        template.extra_metadata = {**template.extra_metadata, "cancel_requested": True}
        db.add(template)
        db.commit()
        db.refresh(template)
        return template

    def get_check(self, db: Session, check_id: UUID) -> TemplateCheck | None:
        query = (
            select(TemplateCheck)
            .options(selectinload(TemplateCheck.section_checks))
            .where(TemplateCheck.id == check_id)
        )
        return db.scalar(query)

    def list_document_checks(self, db: Session, document_id: UUID) -> list[TemplateCheck]:
        query = (
            select(TemplateCheck)
            .options(selectinload(TemplateCheck.section_checks))
            .where(TemplateCheck.document_id == document_id)
            .order_by(TemplateCheck.created_at.desc())
        )
        return list(db.scalars(query).all())

    def _extract_template_requirements(self, section: RawSection) -> dict:
        excerpt = section.cleaned_text[: self.settings.section_excerpt_chars]
        payload = {
            "heading": section.title,
            "level": section.level,
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
                                    "Du analysierst eine Dokumentationsvorlage. "
                                    "Extrahiere für jeden Abschnitt kurz, was inhaltlich beschrieben werden muss, "
                                    "und leite konkrete Prüffragen aus dem Abschnitt ab. "
                                    "Verwende nur Inhalte aus dem Vorlagentext und erfinde keine Anforderungen."
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
                        "name": "template_section_requirements",
                        "schema": TEMPLATE_SECTION_SCHEMA,
                        "strict": True,
                    }
                },
            )
            parsed = json.loads(response.output_text)
            parsed["questions"] = [question.strip() for question in parsed["questions"] if question.strip()]
            return parsed
        except Exception:
            return {
                "requirement_summary": self._fallback_requirement_summary(section.cleaned_text),
                "questions": self._fallback_questions(section.cleaned_text),
            }

    def _evaluate_section(self, template_section: ReviewTemplateSection, document_section: DocumentSection, score: float) -> dict:
        excerpt = (document_section.cleaned_text or document_section.raw_text_exact or "")[: self.settings.section_excerpt_chars]
        payload = {
            "template_heading": template_section.heading,
            "template_requirement_summary": template_section.requirement_summary,
            "template_questions": template_section.questions,
            "document_heading": document_section.heading,
            "document_excerpt": excerpt,
            "heading_match_score": score,
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
                                    "Du prüfst eine Anwendungsdokumentation gegen eine Vorlagenanforderung. "
                                    "Bewerte nur anhand des gelieferten Dokumentabschnitts, ob die geforderten Inhalte "
                                    "und Fragen abgedeckt sind. Erfinde keine Nachweise."
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
                        "name": "template_section_check",
                        "schema": SECTION_CHECK_SCHEMA,
                        "strict": True,
                    }
                },
            )
            return json.loads(response.output_text)
        except Exception:
            status = "complete" if score >= 0.92 else "partial"
            return {
                "coverage_status": status,
                "reasoning": "Fallback-Bewertung auf Basis der Überschriftenähnlichkeit.",
                "missing_topics": [] if status == "complete" else template_section.questions,
                "answered_questions": [
                    {
                        "question": question,
                        "status": "answered" if status == "complete" else "partial",
                        "evidence": document_section.summary or document_section.cleaned_text[:240],
                    }
                    for question in template_section.questions
                ],
                "confidence": min(0.95, max(0.35, score)),
            }

    def _match_document_section(
        self,
        template_section: ReviewTemplateSection,
        document_sections: list[DocumentSection],
    ) -> tuple[DocumentSection | None, float]:
        best_section: DocumentSection | None = None
        best_score = 0.0
        template_heading = self._normalize(template_section.heading)

        for section in document_sections:
            heading_score = SequenceMatcher(None, template_heading, self._normalize(section.heading)).ratio()
            normalized_score = SequenceMatcher(None, template_section.normalized_heading, self._normalize(section.normalized_heading)).ratio()
            keyword_score = self._keyword_overlap(template_section.questions, section.cleaned_text or section.raw_text_exact)
            score = max(heading_score, normalized_score * 0.95, keyword_score * 0.8)
            if template_heading and template_heading in self._normalize(section.heading):
                score = max(score, 0.96)
            if score > best_score:
                best_score = score
                best_section = section

        return (best_section, best_score) if best_score >= 0.58 else (None, 0.0)

    def _load_template_and_document(self, db: Session, template_id: UUID, document_id: UUID) -> tuple[ReviewTemplate, Document]:
        template = self.get_template(db, template_id)
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
        return template, document

    def _select_template_sections(
        self,
        template: ReviewTemplate,
        *,
        section_limit: int | None = None,
        template_section_ids: list[UUID] | None = None,
    ) -> list[ReviewTemplateSection]:
        selected_template_sections = sorted(template.sections, key=lambda item: item.sort_index)
        if template_section_ids:
            selected_ids = set(template_section_ids)
            selected_template_sections = [section for section in selected_template_sections if section.id in selected_ids]
            if not selected_template_sections:
                raise ValueError("Keine gültigen Vorlagenabschnitte ausgewählt")
        if section_limit is not None:
            selected_template_sections = selected_template_sections[:section_limit]
        return selected_template_sections

    def _keyword_overlap(self, questions: list[str], text: str) -> float:
        haystack = self._normalize(text)
        if not haystack or not questions:
            return 0.0
        terms: set[str] = set()
        for question in questions:
            for token in self._normalize(question).split():
                if len(token) >= 5:
                    terms.add(token)
        if not terms:
            return 0.0
        hits = sum(1 for token in terms if token in haystack)
        return hits / len(terms)

    def _fallback_requirement_summary(self, text: str) -> str:
        clean = " ".join(text.split())
        return clean[:400].strip()

    def _fallback_questions(self, text: str) -> list[str]:
        lines = [line.strip(" -•*") for line in text.splitlines() if line.strip()]
        explicit = [line for line in lines if "?" in line and len(line) > 8]
        if explicit:
            return explicit[:8]
        return [line for line in lines if len(line.split()) >= 4][:6]

    def _normalize(self, text: str) -> str:
        return " ".join(
            "".join(character if character.isalnum() or character.isspace() else " " for character in text.casefold()).split()
        )

    def _section_key(self, heading: str) -> str | None:
        normalized = self._normalize(heading)
        return normalized[:128] if normalized else None

    def _serialize_check(self, check: TemplateCheck, template: ReviewTemplate, document: Document) -> dict:
        check_payload = TemplateCheckRead.model_validate(check).model_dump(mode="json")
        check_payload["template_name"] = template.display_name
        check_payload["document_name"] = document.original_filename
        return check_payload

    def _check_template_cancelled(self, db: Session, template: ReviewTemplate) -> None:
        db.refresh(template)
        if template.extra_metadata.get("cancel_requested") or template.status == "cancelling":
            raise JobCancelledError()

    def _mark_template_cancelled(self, db: Session, template: ReviewTemplate) -> None:
        template.sections.clear()
        template.section_count = 0
        template.status = "cancelled"
        template.extra_metadata = {**template.extra_metadata, "cancel_requested": False, "error_message": "Verarbeitung abgebrochen"}
        db.add(template)
        db.commit()
