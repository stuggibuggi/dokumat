from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.db import SessionLocal, is_pgvector_enabled
from app.models import Document, DocumentImage, DocumentPage, DocumentSection
from app.services.openai_structurer import OpenAISectionStructurer
from app.services.outline_check import OutlineCheckService
from app.services.pdf_extractor import PDFExtractor
from app.services.section_builder import SectionBuilder
from app.services.storage import StorageService
from app.services.template_sections import TemplateSectionProvider


class JobCancelledError(Exception):
    pass


class DocumentIngestionService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.storage = StorageService(settings)
        self.extractor = PDFExtractor(settings)
        self.section_builder = SectionBuilder(settings)
        self.openai_structurer = OpenAISectionStructurer(settings)
        self.outline_service = OutlineCheckService(settings)
        self.template_provider = TemplateSectionProvider(settings)

    def queue_uploaded_document(self, db: Session, upload: UploadFile) -> Document:
        document_id = uuid4()
        self.storage.ensure_directories()
        stored_path = self.storage.save_upload(document_id, upload)
        document = Document(
            id=document_id,
            original_filename=upload.filename or "upload.pdf",
            storage_path=self.storage.to_relative(stored_path),
            status="queued",
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        return document

    def queue_existing_document(self, db: Session, source_path: Path) -> Document:
        document_id = uuid4()
        self.storage.ensure_directories()
        stored_path = self.storage.copy_example_pdf(document_id, source_path)
        document = Document(
            id=document_id,
            original_filename=source_path.name,
            storage_path=self.storage.to_relative(stored_path),
            status="queued",
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        return document

    def process_document(self, document_id: UUID) -> None:
        with SessionLocal() as db:
            document = self._get_document_or_raise(db, document_id)
            if document.extra_metadata.get("cancel_requested"):
                self._mark_document_cancelled(db, document, clear_data=True)
                return
            document.status = "extracting"
            document.error_message = None
            document.extra_metadata = {**document.extra_metadata, "cancel_requested": False}
            db.commit()

            try:
                self._clear_document_data(db, document.id)
                db.commit()
                self._check_cancelled(db, document, clear_data=True)

                pdf_path = self.storage.to_absolute(document.storage_path)
                image_dir = self.storage.reset_document_image_dir(document.id)
                pages = self.extractor.extract(pdf_path, image_dir)
                document.page_count = len(pages)

                image_models_by_key: dict[str, DocumentImage] = {}
                for page in pages:
                    self._check_cancelled(db, document, clear_data=True)
                    page_model = DocumentPage(
                        document_id=document.id,
                        page_number=page.page_number,
                        text_content=page.text,
                        detected_headings=[
                            {
                                "text": heading.text,
                                "level": heading.level,
                                "confidence": heading.confidence,
                                "font_size": heading.font_size,
                            }
                            for heading in page.headings
                        ],
                    )
                    db.add(page_model)
                    db.flush()

                    for image in page.images:
                        image_model = DocumentImage(
                            document_id=document.id,
                            page_id=page_model.id,
                            image_key=image.image_id,
                            page_number=image.page_number,
                            sort_index=image.sort_index,
                            filename=image.filename,
                            storage_path=image.relative_path,
                            mime_type=image.mime_type,
                            width=image.width,
                            height=image.height,
                            sha256=image.sha256,
                        )
                        db.add(image_model)
                        db.flush()
                        image_models_by_key[image.image_id] = image_model

                template_sections = self.template_provider.load()
                sections = self.section_builder.build(pages, template_sections=template_sections)
                document.extra_metadata = {
                    **document.extra_metadata,
                    "template_sections_loaded": len(template_sections),
                    "sections_extracted": len(sections),
                }

                for section in sections:
                    self._check_cancelled(db, document, clear_data=True)
                    raw_text_exact = section.raw_text_exact
                    cleaned_text = section.cleaned_text
                    markdown_text = section.markdown_text
                    section_model = DocumentSection(
                        document_id=document.id,
                        sort_index=section.sort_index,
                        heading=section.title,
                        normalized_heading=section.title,
                        level=section.level,
                        start_page=section.start_page,
                        end_page=section.end_page,
                        raw_text_exact=raw_text_exact,
                        cleaned_text=cleaned_text,
                        markdown_text=markdown_text,
                        raw_text=raw_text_exact,
                        content_markdown=markdown_text,
                        summary=None,
                        keywords=[],
                        confidence=0.0,
                        extra_metadata={"page_numbers": section.page_numbers},
                    )
                    db.add(section_model)
                    db.flush()

                    for image_key in section.image_keys:
                        image_model = image_models_by_key.get(image_key)
                        if image_model and image_model.section_id is None:
                            image_model.section_id = section_model.id

                document.status = "extracted"
                db.commit()
            except JobCancelledError:
                db.rollback()
                document = self._get_document_or_raise(db, document_id)
                self._mark_document_cancelled(db, document, clear_data=True)
            except Exception as exc:
                db.rollback()
                document = self._get_document_or_raise(db, document_id)
                document.status = "failed"
                document.error_message = str(exc)
                db.commit()

    def queue_analyze_document(self, db: Session, document_id: UUID) -> Document:
        document = self._get_document_or_raise(db, document_id)
        if document.status in {"queued", "extracting", "analyzing"}:
            raise ValueError("Dokument wird bereits verarbeitet")
        if not self._document_has_sections(db, document_id):
            raise ValueError("Dokument wurde noch nicht lokal zerlegt")

        document.status = "queued"
        document.error_message = None
        document.extra_metadata = {**document.extra_metadata, "cancel_requested": False}
        db.commit()
        db.refresh(document)
        return document

    def queue_refresh_embeddings(self, db: Session, document_id: UUID) -> Document:
        document = self._get_document_or_raise(db, document_id)
        if document.status in {"queued", "extracting", "analyzing"}:
            raise ValueError("Dokument wird bereits verarbeitet")
        if not self._document_has_sections(db, document_id):
            raise ValueError("Dokument wurde noch nicht lokal zerlegt")

        document.status = "queued"
        document.error_message = None
        document.extra_metadata = {**document.extra_metadata, "cancel_requested": False}
        db.commit()
        db.refresh(document)
        return document

    def analyze_document(self, document_id: UUID) -> None:
        with SessionLocal() as db:
            document = self._get_document_or_raise(db, document_id)
            if not self._document_has_sections(db, document_id):
                document.status = "failed"
                document.error_message = "Dokument wurde noch nicht lokal zerlegt"
                db.commit()
                return

            if document.extra_metadata.get("cancel_requested"):
                self._mark_document_cancelled(db, document)
                return
            document.status = "analyzing"
            document.error_message = None
            document.extra_metadata = {**document.extra_metadata, "cancel_requested": False}
            db.commit()

            try:
                sections = list(
                    db.scalars(
                        select(DocumentSection)
                        .where(DocumentSection.document_id == document_id)
                        .order_by(DocumentSection.sort_index)
                    ).all()
                )
                for section in sections:
                    self._check_cancelled(db, document)
                    enrichment = self.openai_structurer.enrich_existing(
                        heading=section.heading,
                        start_page=section.start_page,
                        end_page=section.end_page,
                        raw_text=section.raw_text_exact,
                        image_count=len(section.images),
                    )
                    section.normalized_heading = enrichment["normalized_heading"]
                    section.summary = enrichment["summary"]
                    section.keywords = enrichment["keywords"]
                    section.confidence = float(enrichment["confidence"])
                    if is_pgvector_enabled():
                        section.embedding = self.openai_structurer.embed_text(
                            "\n\n".join(
                                part
                                for part in [
                                    section.normalized_heading or section.heading,
                                    section.summary or "",
                                    section.cleaned_text or section.raw_text_exact,
                                ]
                                if part
                            )
                        )

                document.status = "completed"
                db.commit()
            except JobCancelledError:
                db.rollback()
                document = self._get_document_or_raise(db, document_id)
                self._mark_document_cancelled(db, document)
            except Exception as exc:
                db.rollback()
                document = self._get_document_or_raise(db, document_id)
                document.status = "failed"
                document.error_message = str(exc)
                db.commit()

    def refresh_embeddings(self, document_id: UUID) -> None:
        with SessionLocal() as db:
            document = self._get_document_or_raise(db, document_id)
            if not self._document_has_sections(db, document_id):
                document.status = "failed"
                document.error_message = "Dokument wurde noch nicht lokal zerlegt"
                db.commit()
                return

            if document.extra_metadata.get("cancel_requested"):
                self._mark_document_cancelled(db, document)
                return
            document.status = "analyzing"
            document.error_message = None
            document.extra_metadata = {**document.extra_metadata, "cancel_requested": False}
            db.commit()

            try:
                sections = list(
                    db.scalars(
                        select(DocumentSection)
                        .where(DocumentSection.document_id == document_id)
                        .order_by(DocumentSection.sort_index)
                    ).all()
                )
                for section in sections:
                    self._check_cancelled(db, document)
                    if not is_pgvector_enabled():
                        section.embedding = None
                        continue
                    section.embedding = self.openai_structurer.embed_text(
                        "\n\n".join(
                            part
                            for part in [
                                section.normalized_heading or section.heading,
                                section.summary or "",
                                section.cleaned_text or section.raw_text_exact,
                            ]
                            if part
                        )
                    )

                document.status = "completed"
                db.commit()
            except JobCancelledError:
                db.rollback()
                document = self._get_document_or_raise(db, document_id)
                self._mark_document_cancelled(db, document)
            except Exception as exc:
                db.rollback()
                document = self._get_document_or_raise(db, document_id)
                document.status = "failed"
                document.error_message = str(exc)
                db.commit()

    def queue_reprocess_document(self, db: Session, document_id: UUID) -> Document:
        document = self._get_document_or_raise(db, document_id)
        if document.status in {"queued", "extracting", "analyzing"}:
            raise ValueError("Dokument wird bereits verarbeitet")

        document.status = "queued"
        document.error_message = None
        document.extra_metadata = {**document.extra_metadata, "cancel_requested": False}
        db.commit()
        db.refresh(document)
        return document

    def cancel_document_job(self, db: Session, document_id: UUID) -> Document:
        document = self._get_document_or_raise(db, document_id)
        if document.status in {"completed", "failed", "cancelled"}:
            raise ValueError("Dokument wird aktuell nicht verarbeitet")

        if document.status == "queued":
            document.status = "cancelled"
        else:
            document.status = "cancelling"
        document.error_message = "Verarbeitung wird abgebrochen"
        document.extra_metadata = {**document.extra_metadata, "cancel_requested": True}
        db.commit()
        db.refresh(document)
        return document

    def reprocess_document(self, document_id: UUID) -> None:
        self.process_document(document_id)

    def get_document(self, db: Session, document_id: UUID) -> Document | None:
        query = (
            select(Document)
            .options(
                selectinload(Document.pages),
                selectinload(Document.sections).selectinload(DocumentSection.images),
                selectinload(Document.images),
            )
            .where(Document.id == document_id)
        )
        return db.scalar(query)

    def load_document_outline(self, document: Document):
        outline_path = document.extra_metadata.get("outline_result_storage_path")
        if not outline_path:
            return None
        return self.outline_service.load_result(outline_path)

    def _get_document_or_raise(self, db: Session, document_id: UUID) -> Document:
        document = db.get(Document, document_id)
        if document is None:
            raise ValueError(f"Dokument {document_id} nicht gefunden")
        return document

    def _clear_document_data(self, db: Session, document_id: UUID) -> None:
        db.execute(delete(DocumentImage).where(DocumentImage.document_id == document_id))
        db.execute(delete(DocumentSection).where(DocumentSection.document_id == document_id))
        db.execute(delete(DocumentPage).where(DocumentPage.document_id == document_id))
        document = self._get_document_or_raise(db, document_id)
        document.page_count = 0

    def _document_has_sections(self, db: Session, document_id: UUID) -> bool:
        return db.scalar(select(DocumentSection.id).where(DocumentSection.document_id == document_id).limit(1)) is not None

    def _check_cancelled(self, db: Session, document: Document, *, clear_data: bool = False) -> None:
        db.refresh(document)
        if document.extra_metadata.get("cancel_requested") or document.status == "cancelling":
            raise JobCancelledError()

    def _mark_document_cancelled(self, db: Session, document: Document, *, clear_data: bool = False) -> None:
        if clear_data:
            self._clear_document_data(db, document.id)
        document.status = "cancelled"
        document.error_message = "Verarbeitung abgebrochen"
        document.extra_metadata = {**document.extra_metadata, "cancel_requested": False}
        db.add(document)
        db.commit()
