from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, ManagedDocument, ManagedDocumentVersion, User
from app.services.ingestion import DocumentIngestionService


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
        managed_document.checked_out_at = datetime.now(UTC)
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
        version.reviewed_at = datetime.now(UTC)
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
        version.reviewed_at = datetime.now(UTC)
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
        version.reviewed_at = datetime.now(UTC)
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
