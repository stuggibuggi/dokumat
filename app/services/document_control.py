from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import is_pgvector_enabled
from app.models import Document, ManagedDocument, ManagedDocumentVersion, User
from app.services.ingestion import DocumentIngestionService

settings = get_settings()


class DocumentControlService:
    def __init__(self, ingestion_service: DocumentIngestionService) -> None:
        self.ingestion_service = ingestion_service

    def list_managed_documents(self, db: Session) -> list[ManagedDocument]:
        query = select(ManagedDocument).order_by(ManagedDocument.updated_at.desc())
        return list(db.scalars(query).unique().all())

    def get_managed_document(self, db: Session, managed_document_id: UUID) -> ManagedDocument:
        document = db.get(ManagedDocument, managed_document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
        return document

    def create_managed_document(
        self,
        db: Session,
        current_user: User,
        upload: UploadFile,
        *,
        title: str | None = None,
        description: str = "",
        change_summary: str = "",
    ) -> ManagedDocument:
        if not upload.filename or not upload.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Bitte eine PDF-Datei hochladen")

        technical_document = self.ingestion_service.queue_uploaded_document(db, upload)
        self.ingestion_service.process_document(technical_document.id)
        db.refresh(technical_document)

        managed_document = ManagedDocument(
            title=(title or Path(upload.filename).stem).strip() or "Neues Dokument",
            description=description.strip(),
            status="draft",
            owner_id=current_user.id,
        )
        db.add(managed_document)
        db.flush()

        version = ManagedDocumentVersion(
            managed_document_id=managed_document.id,
            document_id=technical_document.id,
            version_number=1,
            status="draft",
            change_summary=change_summary.strip(),
            created_by_id=current_user.id,
        )
        db.add(version)
        db.flush()

        managed_document.current_version_id = version.id
        db.add(managed_document)
        db.commit()
        db.refresh(managed_document)
        return managed_document

    def checkout_document(self, db: Session, managed_document_id: UUID, current_user: User) -> ManagedDocument:
        managed_document = self.get_managed_document(db, managed_document_id)
        if managed_document.checked_out_by_id and managed_document.checked_out_by_id != current_user.id:
            raise HTTPException(status_code=409, detail="Dokument ist bereits ausgecheckt")

        managed_document.checked_out_by_id = current_user.id
        managed_document.checked_out_at = datetime.now(timezone.utc)
        managed_document.status = "checked_out"
        db.add(managed_document)
        db.commit()
        db.refresh(managed_document)
        return managed_document

    def cancel_checkout(self, db: Session, managed_document_id: UUID, current_user: User) -> ManagedDocument:
        managed_document = self.get_managed_document(db, managed_document_id)
        if managed_document.checked_out_by_id != current_user.id and "admin" not in (current_user.roles or [current_user.role]):
            raise HTTPException(status_code=403, detail="Checkout kann nur vom Besitzer oder Admin aufgehoben werden")

        managed_document.checked_out_by_id = None
        managed_document.checked_out_at = None
        managed_document.status = managed_document.current_version.status if managed_document.current_version else "draft"
        db.add(managed_document)
        db.commit()
        db.refresh(managed_document)
        return managed_document

    def checkin_document(
        self,
        db: Session,
        managed_document_id: UUID,
        current_user: User,
        upload: UploadFile,
        *,
        change_summary: str = "",
    ) -> ManagedDocument:
        managed_document = self.get_managed_document(db, managed_document_id)
        if managed_document.checked_out_by_id != current_user.id:
            raise HTTPException(status_code=403, detail="Dokument ist nicht von dir ausgecheckt")
        if not upload.filename or not upload.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Bitte eine PDF-Datei hochladen")

        technical_document = self.ingestion_service.queue_uploaded_document(db, upload)
        self.ingestion_service.process_document(technical_document.id)
        db.refresh(technical_document)

        current_version_number = managed_document.current_version.version_number if managed_document.current_version else 0
        version = ManagedDocumentVersion(
            managed_document_id=managed_document.id,
            document_id=technical_document.id,
            version_number=current_version_number + 1,
            status="draft",
            change_summary=change_summary.strip(),
            created_by_id=current_user.id,
        )
        db.add(version)
        db.flush()

        managed_document.current_version_id = version.id
        managed_document.checked_out_by_id = None
        managed_document.checked_out_at = None
        managed_document.status = "draft"
        db.add(managed_document)
        db.commit()
        db.refresh(managed_document)
        return managed_document

    def submit_for_review(
        self,
        db: Session,
        managed_document_id: UUID,
        current_user: User,
    ) -> ManagedDocument:
        managed_document = self.get_managed_document(db, managed_document_id)
        version = self._require_current_version(managed_document)
        if version.created_by_id != current_user.id and managed_document.owner_id != current_user.id and "admin" not in (current_user.roles or [current_user.role]):
            raise HTTPException(status_code=403, detail="Nur Ersteller, Besitzer oder Admin kann zur Prüfung einreichen")
        if managed_document.checked_out_by_id:
            raise HTTPException(status_code=409, detail="Dokument muss vor der Einreichung eingecheckt sein")

        version.status = "in_review"
        version.submitted_by_id = current_user.id
        db.add(version)
        managed_document.status = "in_review"
        db.add(managed_document)
        db.commit()
        db.refresh(managed_document)
        return managed_document

    def approve_document(self, db: Session, managed_document_id: UUID, current_user: User, comment: str = "") -> ManagedDocument:
        managed_document = self.get_managed_document(db, managed_document_id)
        version = self._require_current_version(managed_document)
        if version.status not in {"in_review", "rejected"}:
            raise HTTPException(status_code=409, detail="Aktuelle Version ist nicht zur Genehmigung eingereicht")
        version.status = "approved"
        version.reviewed_by_id = current_user.id
        version.reviewed_at = datetime.now(timezone.utc)
        version.review_comment = comment.strip() or None
        db.add(version)
        managed_document.status = "approved"
        db.add(managed_document)
        db.commit()
        db.refresh(managed_document)
        return managed_document

    def reject_document(self, db: Session, managed_document_id: UUID, current_user: User, comment: str) -> ManagedDocument:
        managed_document = self.get_managed_document(db, managed_document_id)
        version = self._require_current_version(managed_document)
        if version.status != "in_review":
            raise HTTPException(status_code=409, detail="Aktuelle Version ist nicht in Prüfung")
        if not comment.strip():
            raise HTTPException(status_code=400, detail="Bitte eine Begründung für die Ablehnung angeben")
        version.status = "rejected"
        version.reviewed_by_id = current_user.id
        version.reviewed_at = datetime.now(timezone.utc)
        version.review_comment = comment.strip()
        db.add(version)
        managed_document.status = "rejected"
        db.add(managed_document)
        db.commit()
        db.refresh(managed_document)
        return managed_document

    def release_document(self, db: Session, managed_document_id: UUID, current_user: User, comment: str = "") -> ManagedDocument:
        managed_document = self.get_managed_document(db, managed_document_id)
        version = self._require_current_version(managed_document)
        if version.status != "approved":
            raise HTTPException(status_code=409, detail="Nur genehmigte Versionen können freigegeben werden")
        version.status = "released"
        version.reviewed_by_id = current_user.id
        version.reviewed_at = datetime.now(timezone.utc)
        if comment.strip():
            version.review_comment = comment.strip()
        db.add(version)
        managed_document.status = "released"
        db.add(managed_document)
        db.commit()
        db.refresh(managed_document)
        return managed_document

    def serialize_managed_document_list_item(self, managed_document: ManagedDocument) -> dict:
        return {
            "id": managed_document.id,
            "title": managed_document.title,
            "description": managed_document.description,
            "status": managed_document.status,
            "owner_name": managed_document.owner.display_name if managed_document.owner else managed_document.owner_id,
            "checked_out_by_name": managed_document.checked_out_by.display_name if managed_document.checked_out_by else None,
            "checked_out_at": managed_document.checked_out_at,
            "version_count": len(managed_document.versions),
            "created_at": managed_document.created_at,
            "updated_at": managed_document.updated_at,
            "current_version": self.serialize_version(managed_document.current_version) if managed_document.current_version else None,
        }

    def serialize_managed_document_detail(
        self,
        managed_document: ManagedDocument,
        current_document: Document | None,
        current_document_payload: dict | None = None,
    ) -> dict:
        payload = self.serialize_managed_document_list_item(managed_document)
        payload.update(
            {
                "owner_id": managed_document.owner_id,
                "checked_out_by_id": managed_document.checked_out_by_id,
                "current_document": current_document_payload,
                "analysis_workflow": self.build_analysis_workflow(managed_document, current_document),
                "versions": [self.serialize_version(item) for item in managed_document.versions],
            }
        )
        return payload

    def serialize_version(self, version: ManagedDocumentVersion) -> dict:
        return {
            "id": version.id,
            "document_id": version.document_id,
            "version_number": version.version_number,
            "status": version.status,
            "change_summary": version.change_summary,
            "review_comment": version.review_comment,
            "reviewed_at": version.reviewed_at,
            "created_at": version.created_at,
            "updated_at": version.updated_at,
            "created_by_name": version.created_by.display_name if version.created_by else "",
            "submitted_by_name": version.submitted_by.display_name if version.submitted_by else None,
            "reviewed_by_name": version.reviewed_by.display_name if version.reviewed_by else None,
            "original_filename": version.document.original_filename if version.document else "",
            "processing_status": version.document.status if version.document else "unknown",
        }

    def _require_current_version(self, managed_document: ManagedDocument) -> ManagedDocumentVersion:
        version = managed_document.current_version
        if version is None:
            raise HTTPException(status_code=409, detail="Dokument besitzt noch keine Version")
        return version

    def build_analysis_workflow(self, managed_document: ManagedDocument, current_document: Document | None) -> dict | None:
        del managed_document
        if current_document is None:
            return None

        document_status = current_document.status or "unknown"
        has_extraction = bool(current_document.page_count or current_document.pages or current_document.sections or current_document.images)
        outline_available = bool(getattr(current_document, "outline_available", False))
        embeddings_available = bool(getattr(current_document, "embeddings_available", False))
        pgvector_available = is_pgvector_enabled()
        document_updated_at = current_document.updated_at
        outline_run_at = self._resolve_outline_timestamp(current_document)

        steps = [
            self._build_extract_step(document_status, has_extraction, document_updated_at),
            self._build_outline_step(has_extraction, outline_available, outline_run_at),
            self._build_analysis_step(document_status, has_extraction, document_updated_at),
            self._build_embedding_step(document_status, has_extraction, embeddings_available, pgvector_available, document_updated_at),
        ]

        next_action = "Dokument ist technisch vollständig verarbeitet."
        if steps[0]["status"] == "current":
            next_action = "Lokale Zerlegung läuft gerade."
        elif steps[0]["status"] == "failed":
            next_action = "Lokale Zerlegung fehlgeschlagen. Bitte Dokument neu verarbeiten."
        elif steps[1]["status"] == "pending":
            next_action = "Als Nächstes sollte die Gliederung geprüft werden."
        elif steps[2]["status"] == "current":
            next_action = "OpenAI-Analyse läuft gerade."
        elif steps[2]["status"] == "failed":
            next_action = "Analyse fehlgeschlagen. Bitte Analyse erneut starten."
        elif steps[2]["status"] == "pending":
            next_action = "Als Nächstes sollte die Analyse gestartet werden."
        elif steps[3]["status"] == "current":
            next_action = "Embeddings werden gerade erzeugt oder aktualisiert."
        elif steps[3]["status"] == "pending":
            next_action = "Embeddings können jetzt ergänzt oder aktualisiert werden."

        return {
            "current_status": document_status,
            "recommended_order_note": (
                "Empfohlene Reihenfolge: 1. lokal zerlegen, 2. Gliederung prüfen, "
                "3. Analyse ausführen, 4. Embeddings nur bei Bedarf ergänzen oder aktualisieren."
            ),
            "next_action": next_action,
            "steps": steps,
        }

    def _build_extract_step(self, document_status: str, has_extraction: bool, timestamp: datetime | None) -> dict:
        status = "pending"
        if document_status in {"queued", "extracting"}:
            status = "current"
        elif document_status == "failed" and not has_extraction:
            status = "failed"
        elif has_extraction or document_status in {"extracted", "analyzing", "completed", "cancelled", "cancelling"}:
            status = "completed"
        return {
            "key": "extract",
            "label": "1. Lokal zerlegen",
            "status": status,
            "detail": "PDF in Seiten, Abschnitte und Bilder zerlegen.",
            "last_run_at": timestamp if status in {"completed", "current"} else None,
        }

    def _build_outline_step(self, has_extraction: bool, outline_available: bool, timestamp: datetime | None) -> dict:
        status = "blocked"
        if has_extraction:
            status = "completed" if outline_available else "pending"
        return {
            "key": "outline",
            "label": "2. Gliederung prüfen",
            "status": status,
            "detail": "Hierarchie und Kapitelstruktur des Dokuments prüfen.",
            "last_run_at": timestamp if status == "completed" else None,
        }

    def _build_analysis_step(self, document_status: str, has_extraction: bool, timestamp: datetime | None) -> dict:
        if not has_extraction:
            status = "blocked"
        elif document_status == "analyzing":
            status = "current"
        elif document_status == "completed":
            status = "completed"
        elif document_status == "failed":
            status = "failed"
        else:
            status = "pending"
        return {
            "key": "analysis",
            "label": "3. Analyse ausführen",
            "status": status,
            "detail": "Abschnitte normalisieren, Zusammenfassungen und Schlagwörter erzeugen.",
            "last_run_at": timestamp if status in {"completed", "current"} else None,
        }

    def _build_embedding_step(
        self,
        document_status: str,
        has_extraction: bool,
        embeddings_available: bool,
        pgvector_available: bool,
        timestamp: datetime | None,
    ) -> dict:
        if not pgvector_available:
            status = "unavailable"
        elif not has_extraction:
            status = "blocked"
        elif embeddings_available:
            status = "completed"
        elif document_status == "analyzing":
            status = "current"
        else:
            status = "pending"
        return {
            "key": "embeddings",
            "label": "4. Embeddings",
            "status": status,
            "detail": "Meist schon Teil der Analyse. Separat nur nötig, wenn Vektoren fehlen oder neu berechnet werden sollen.",
            "last_run_at": timestamp if status in {"completed", "current"} else None,
        }

    def _resolve_outline_timestamp(self, current_document: Document) -> datetime | None:
        outline_path = current_document.extra_metadata.get("outline_result_storage_path")
        if not outline_path:
            return None
        try:
            stat = (settings.base_dir / outline_path).stat()
        except OSError:
            return None
        return datetime.fromtimestamp(stat.st_mtime, timezone.utc)
