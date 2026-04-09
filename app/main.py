from __future__ import annotations

from pathlib import Path
import tempfile
from uuid import UUID

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db, init_db
from app.models import Document, DocumentSection, User
from app.schemas import (
    AuthLoginRequest,
    AuthRegisterRequest,
    AuthSessionRead,
    AdminUserUpdateRequest,
    DocumentListItem,
    DocumentRead,
    ImportExampleRequest,
    ManagedDocumentCreateResponse,
    ManagedDocumentListItem,
    ManagedDocumentRead,
    OutlineCheckResponse,
    QueuedDocumentResponse,
    ReviewActionRequest,
    SectionSearchRequest,
    SectionSearchResponse,
    TemplateCheckRequest,
    TemplateCheckRead,
    TemplateListItem,
    TemplateRead,
    TemplateSectionMatchRead,
    StructureMappingResponse,
    UserRead,
)
from app.services.auth import auth_service, require_admin_user, require_current_user, require_reviewer_user
from app.services.document_control import DocumentControlService
from app.services.ingestion import DocumentIngestionService
from app.services.outline_check import OutlineCheckService
from app.services.semantic_search import SemanticSearchService
from app.services.storage import StorageService
from app.services.template_review import TemplateReviewService
from app.services.structure_mapper import StructureMapperService


settings = get_settings()
storage = StorageService(settings)
ingestion_service = DocumentIngestionService(settings)
document_control_service = DocumentControlService(ingestion_service)
outline_check_service = OutlineCheckService(settings)
semantic_search_service = SemanticSearchService(ingestion_service.openai_structurer)
template_review_service = TemplateReviewService(settings)
structure_mapper_service = StructureMapperService(settings)
storage.ensure_directories()

app = FastAPI(title="Dokumat PDF Ingestion API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origin.split(",") if origin.strip()] or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    storage.ensure_directories()
    init_db()
    from app.db import SessionLocal

    with SessionLocal() as db:
        auth_service.ensure_bootstrap_user(db)


app.mount("/storage", StaticFiles(directory=settings.storage_root), name="storage")
app.mount("/assets", StaticFiles(directory=settings.base_dir / "frontend"), name="assets")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(settings.base_dir / "frontend" / "index.html")


@app.get("/index.html", include_in_schema=False)
def index_html() -> FileResponse:
    return FileResponse(settings.base_dir / "frontend" / "index.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/auth/login", response_model=AuthSessionRead)
def login(payload: AuthLoginRequest, db: Session = Depends(get_db)) -> dict:
    user, token, expires_at = auth_service.authenticate(db, payload.username, payload.password)
    return {
        "token": token,
        "expires_at": expires_at,
        "user": user,
        "available_auth_modes": auth_service.available_auth_modes(),
    }


@app.post("/auth/register", response_model=AuthSessionRead)
def register(payload: AuthRegisterRequest, db: Session = Depends(get_db)) -> dict:
    user, token, expires_at = auth_service.register_local_user(
        db,
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        email=payload.email,
    )
    return {
        "token": token,
        "expires_at": expires_at,
        "user": user,
        "available_auth_modes": auth_service.available_auth_modes(),
    }


@app.get("/auth/me", response_model=UserRead)
def read_current_user(current_user: User = Depends(require_current_user)) -> User:
    return current_user


@app.post("/auth/logout")
def logout(
    current_user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict:
    del current_user
    token = authorization.split(" ", 1)[1] if authorization and " " in authorization else ""
    if token:
        auth_service.logout(db, token)
    return {"status": "ok"}


@app.get("/admin/users", response_model=list[UserRead])
def list_admin_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_user),
) -> list[User]:
    del current_user
    return auth_service.list_users(db)


@app.put("/admin/users/{user_id}", response_model=UserRead)
def update_admin_user(
    user_id: UUID,
    payload: AdminUserUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_user),
) -> User:
    del current_user
    return auth_service.update_user(
        db,
        user_id,
        display_name=payload.display_name,
        email=payload.email,
        roles=payload.roles,
        is_active=payload.is_active,
    )


@app.get("/managed-documents", response_model=list[ManagedDocumentListItem])
def list_managed_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> list[dict]:
    del current_user
    managed_documents = document_control_service.list_managed_documents(db)
    return [document_control_service.serialize_managed_document_list_item(item) for item in managed_documents]


@app.get("/managed-documents/{managed_document_id}", response_model=ManagedDocumentRead)
def get_managed_document(
    managed_document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> dict:
    del current_user
    managed_document = document_control_service.get_managed_document(db, managed_document_id)
    current_document = managed_document.current_version.document if managed_document.current_version else None
    current_document_payload = None
    if current_document is not None:
        outline = ingestion_service.load_document_outline(current_document)
        current_document.outline_check = outline  # type: ignore[attr-defined]
        current_document.outline_available = outline is not None  # type: ignore[attr-defined]
        current_document.embeddings_available = bool(  # type: ignore[attr-defined]
            db.scalar(
                select(DocumentSection.id)
                .where(DocumentSection.document_id == current_document.id, DocumentSection.embedding.is_not(None))
                .limit(1)
            )
        )
        current_document_payload = DocumentRead.model_validate(current_document).model_dump(mode="json")
    return document_control_service.serialize_managed_document_detail(managed_document, current_document, current_document_payload)


@app.post("/managed-documents/upload", response_model=ManagedDocumentCreateResponse)
def upload_managed_document(
    title: str = Form(default=""),
    description: str = Form(default=""),
    change_summary: str = Form(default=""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> dict:
    managed_document = document_control_service.create_managed_document(
        db,
        current_user,
        file,
        title=title,
        description=description,
        change_summary=change_summary,
    )
    return document_control_service.serialize_managed_document_list_item(managed_document)


@app.post("/managed-documents/{managed_document_id}/checkout", response_model=ManagedDocumentRead)
def checkout_managed_document(
    managed_document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> dict:
    managed_document = document_control_service.checkout_document(db, managed_document_id, current_user)
    return document_control_service.serialize_managed_document_detail(managed_document, managed_document.current_version.document if managed_document.current_version else None)


@app.post("/managed-documents/{managed_document_id}/cancel-checkout", response_model=ManagedDocumentRead)
def cancel_managed_document_checkout(
    managed_document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> dict:
    managed_document = document_control_service.cancel_checkout(db, managed_document_id, current_user)
    return document_control_service.serialize_managed_document_detail(managed_document, managed_document.current_version.document if managed_document.current_version else None)


@app.post("/managed-documents/{managed_document_id}/checkin", response_model=ManagedDocumentRead)
def checkin_managed_document(
    managed_document_id: UUID,
    change_summary: str = Form(default=""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> dict:
    managed_document = document_control_service.checkin_document(
        db,
        managed_document_id,
        current_user,
        file,
        change_summary=change_summary,
    )
    return document_control_service.serialize_managed_document_detail(managed_document, managed_document.current_version.document if managed_document.current_version else None)


@app.post("/managed-documents/{managed_document_id}/submit-review", response_model=ManagedDocumentRead)
def submit_managed_document_review(
    managed_document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> dict:
    managed_document = document_control_service.submit_for_review(db, managed_document_id, current_user)
    return document_control_service.serialize_managed_document_detail(managed_document, managed_document.current_version.document if managed_document.current_version else None)


@app.post("/managed-documents/{managed_document_id}/approve", response_model=ManagedDocumentRead)
def approve_managed_document(
    managed_document_id: UUID,
    payload: ReviewActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_reviewer_user),
) -> dict:
    managed_document = document_control_service.approve_document(db, managed_document_id, current_user, payload.comment)
    return document_control_service.serialize_managed_document_detail(managed_document, managed_document.current_version.document if managed_document.current_version else None)


@app.post("/managed-documents/{managed_document_id}/reject", response_model=ManagedDocumentRead)
def reject_managed_document(
    managed_document_id: UUID,
    payload: ReviewActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_reviewer_user),
) -> dict:
    managed_document = document_control_service.reject_document(db, managed_document_id, current_user, payload.comment)
    return document_control_service.serialize_managed_document_detail(managed_document, managed_document.current_version.document if managed_document.current_version else None)


@app.post("/managed-documents/{managed_document_id}/release", response_model=ManagedDocumentRead)
def release_managed_document(
    managed_document_id: UUID,
    payload: ReviewActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_reviewer_user),
) -> dict:
    managed_document = document_control_service.release_document(db, managed_document_id, current_user, payload.comment)
    return document_control_service.serialize_managed_document_detail(managed_document, managed_document.current_version.document if managed_document.current_version else None)


@app.get("/documents", response_model=list[DocumentListItem])
def list_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> list[Document]:
    del current_user
    query = select(Document).order_by(Document.created_at.desc())
    documents = list(db.scalars(query).all())
    for document in documents:
        document.outline_available = bool(document.extra_metadata.get("outline_result_storage_path"))  # type: ignore[attr-defined]
        document.embeddings_available = bool(  # type: ignore[attr-defined]
            db.scalar(
                select(DocumentSection.id)
                .where(DocumentSection.document_id == document.id, DocumentSection.embedding.is_not(None))
                .limit(1)
            )
        )
    return documents


@app.get("/example-pdfs")
def list_example_pdfs(current_user: User = Depends(require_current_user)) -> list[dict[str, str | int]]:
    del current_user
    pdfs = sorted(settings.base_dir.glob("*.pdf"))
    return [{"filename": pdf.name, "size_bytes": pdf.stat().st_size} for pdf in pdfs]


@app.get("/documents/{document_id}", response_model=DocumentRead)
def get_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Document:
    del current_user
    document = ingestion_service.get_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    outline = ingestion_service.load_document_outline(document)
    document.outline_check = outline  # type: ignore[attr-defined]
    document.outline_available = outline is not None  # type: ignore[attr-defined]
    document.embeddings_available = bool(  # type: ignore[attr-defined]
        db.scalar(
            select(DocumentSection.id)
            .where(DocumentSection.document_id == document.id, DocumentSection.embedding.is_not(None))
            .limit(1)
        )
    )
    return document


@app.get("/documents/{document_id}/template-checks", response_model=list[TemplateCheckRead])
def list_document_template_checks(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> list:
    del current_user
    document = ingestion_service.get_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    return template_review_service.list_document_checks(db, document_id)


@app.post("/documents/upload", response_model=QueuedDocumentResponse)
def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Document:
    del current_user
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Bitte eine PDF-Datei hochladen")

    document = ingestion_service.queue_uploaded_document(db, file)
    ingestion_service.process_document(document.id)
    db.refresh(document)
    return document


@app.post("/documents/import-example", response_model=QueuedDocumentResponse)
def import_example_document(
    payload: ImportExampleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Document:
    del current_user
    source_path = _resolve_example_pdf(payload.filename)
    document = ingestion_service.queue_existing_document(db, source_path)
    ingestion_service.process_document(document.id)
    db.refresh(document)
    return document


@app.post("/documents/{document_id}/reprocess", response_model=QueuedDocumentResponse)
def reprocess_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Document:
    del current_user
    try:
        document = ingestion_service.queue_reprocess_document(db, document_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "nicht gefunden" in detail else 409
        raise HTTPException(status_code=status_code, detail=detail) from exc

    ingestion_service.reprocess_document(document.id)
    db.refresh(document)
    return document


@app.post("/documents/{document_id}/analyze", response_model=QueuedDocumentResponse)
def analyze_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Document:
    del current_user
    try:
        document = ingestion_service.queue_analyze_document(db, document_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "nicht gefunden" in detail else 409
        raise HTTPException(status_code=status_code, detail=detail) from exc

    ingestion_service.analyze_document(document.id)
    db.refresh(document)
    return document


@app.post("/documents/{document_id}/refresh-embeddings", response_model=QueuedDocumentResponse)
def refresh_embeddings(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Document:
    del current_user
    try:
        document = ingestion_service.queue_refresh_embeddings(db, document_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "nicht gefunden" in detail else 409
        raise HTTPException(status_code=status_code, detail=detail) from exc

    ingestion_service.refresh_embeddings(document.id)
    db.refresh(document)
    return document


@app.post("/documents/{document_id}/cancel", response_model=QueuedDocumentResponse)
def cancel_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> Document:
    del current_user
    try:
        return ingestion_service.cancel_document_job(db, document_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "nicht gefunden" in detail else 409
        raise HTTPException(status_code=status_code, detail=detail) from exc


@app.post("/search/sections", response_model=SectionSearchResponse)
def search_sections(
    payload: SectionSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> SectionSearchResponse:
    del current_user
    return semantic_search_service.search_sections(db, payload)


@app.get("/templates", response_model=list[TemplateListItem])
def list_templates(db: Session = Depends(get_db), current_user: User = Depends(require_current_user)) -> list:
    del current_user
    return template_review_service.list_templates(db)


@app.get("/templates/{template_id}", response_model=TemplateRead)
def get_template(
    template_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    del current_user
    template = template_review_service.get_template(db, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Vorlage nicht gefunden")
    return template


@app.post("/templates/upload", response_model=TemplateRead)
def upload_template(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    del current_user
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Bitte eine PDF-Datei hochladen")

    try:
        file_bytes = file.file.read()
    finally:
        file.file.close()

    template = template_review_service.queue_template_upload(db, file.filename, file_bytes)
    template_review_service.process_template(template.id)
    refreshed_template = template_review_service.get_template(db, template.id)
    if refreshed_template is None:
        raise HTTPException(status_code=500, detail="Vorlage konnte nach der Verarbeitung nicht geladen werden")
    return refreshed_template


@app.post("/templates/{template_id}/check/{document_id}", response_model=TemplateCheckRead)
def run_template_check(
    template_id: UUID,
    document_id: UUID,
    payload: TemplateCheckRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    del current_user
    try:
        result = template_review_service.run_check(
            db,
            template_id,
            document_id,
            template_section_ids=payload.template_section_ids if payload else None,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "nicht gefunden" in detail else 409
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return result


@app.post("/templates/{template_id}/check-sample/{document_id}", response_model=TemplateCheckRead)
def run_template_check_sample(
    template_id: UUID,
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    del current_user
    try:
        result = template_review_service.run_check(db, template_id, document_id, section_limit=3)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "nicht gefunden" in detail else 409
        raise HTTPException(status_code=status_code, detail=detail) from exc
    return result


@app.get("/templates/{template_id}/matches/{document_id}", response_model=list[TemplateSectionMatchRead])
def preview_template_matches(
    template_id: UUID,
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    del current_user
    try:
        return template_review_service.preview_matches(db, template_id, document_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "nicht gefunden" in detail else 409
        raise HTTPException(status_code=status_code, detail=detail) from exc


@app.post("/templates/{template_id}/structure-map/{document_id}", response_model=StructureMappingResponse)
def run_structure_mapping(
    template_id: UUID,
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    del current_user
    try:
        return structure_mapper_service.map_template_to_document(db, template_id, document_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "nicht gefunden" in detail else 409
        raise HTTPException(status_code=status_code, detail=detail) from exc


@app.post("/templates/{template_id}/cancel", response_model=TemplateRead)
def cancel_template(
    template_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
):
    del current_user
    try:
        return template_review_service.cancel_template_job(db, template_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "nicht gefunden" in detail else 409
        raise HTTPException(status_code=status_code, detail=detail) from exc


@app.post("/documents/{document_id}/outline-check", response_model=OutlineCheckResponse)
def run_document_outline_check(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> OutlineCheckResponse:
    del current_user
    document = ingestion_service.get_document(db, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")

    source_path = settings.base_dir / document.storage_path
    result = outline_check_service.analyze_pdf(source_path, document.original_filename)
    document.extra_metadata = {
        **document.extra_metadata,
        "outline_result_storage_path": result.result_storage_path,
        "outline_sanitized_storage_path": result.sanitized_storage_path,
    }
    db.add(document)
    db.commit()
    db.refresh(document)
    return result


@app.post("/outline-check/upload", response_model=OutlineCheckResponse)
def upload_outline_check(
    file: UploadFile = File(...),
    current_user: User = Depends(require_current_user),
) -> OutlineCheckResponse:
    del current_user
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Bitte eine PDF-Datei hochladen")

    with tempfile.TemporaryDirectory(prefix="dokumat-outline-src-") as tmp_dir:
        source_path = Path(tmp_dir) / Path(file.filename).name
        try:
            source_path.write_bytes(file.file.read())
        finally:
            file.file.close()
        return outline_check_service.analyze_pdf(source_path, file.filename)


def _resolve_example_pdf(filename: str) -> Path:
    source_path = settings.base_dir / Path(filename).name
    if not source_path.exists() or source_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="Beispiel-PDF nicht gefunden")
    return source_path
