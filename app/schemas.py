from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ImportExampleRequest(BaseModel):
    filename: str


class AuthLoginRequest(BaseModel):
    username: str
    password: str


class AuthRegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str
    email: str | None = None


class UserRead(BaseModel):
    id: UUID
    username: str
    display_name: str
    email: str | None
    role: str
    roles: list[str]
    is_active: bool
    auth_provider: str

    model_config = ConfigDict(from_attributes=True)


class AuthSessionRead(BaseModel):
    token: str
    expires_at: datetime
    user: UserRead
    available_auth_modes: list[str]


class AdminUserUpdateRequest(BaseModel):
    display_name: str
    email: str | None = None
    roles: list[str]
    is_active: bool = True


class QueuedDocumentResponse(BaseModel):
    id: UUID
    status: str
    original_filename: str

    model_config = ConfigDict(from_attributes=True)


class OutlineNode(BaseModel):
    heading: str
    level: int
    children: list["OutlineNode"] = []


class OutlineChunkDebug(BaseModel):
    chunk_index: int
    start_page: int
    end_page: int
    candidate_count: int
    hierarchy: list[OutlineNode]
    raw_outline_markdown: str


class OutlineCheckResponse(BaseModel):
    filename: str
    sanitized_filename: str
    sanitized_storage_path: str
    result_storage_path: str
    analysis_mode: str
    chunk_count: int
    image_placeholders: int
    hierarchy: list[OutlineNode]
    raw_outline_markdown: str
    chunks: list[OutlineChunkDebug] = []


OutlineNode.model_rebuild()


class DocumentImageRead(BaseModel):
    id: UUID
    page_number: int
    sort_index: int
    filename: str
    storage_path: str
    mime_type: str | None
    width: int | None
    height: int | None
    sha256: str

    model_config = ConfigDict(from_attributes=True)


class DocumentSectionRead(BaseModel):
    id: UUID
    sort_index: int
    heading: str
    normalized_heading: str
    level: int
    start_page: int
    end_page: int
    raw_text_exact: str
    cleaned_text: str
    markdown_text: str
    raw_text: str
    content_markdown: str
    summary: str | None
    keywords: list[str]
    confidence: float

    model_config = ConfigDict(from_attributes=True)


class DocumentPageRead(BaseModel):
    id: UUID
    page_number: int
    text_content: str
    detected_headings: list[dict]

    model_config = ConfigDict(from_attributes=True)


class DocumentListItem(BaseModel):
    id: UUID
    original_filename: str
    status: str
    page_count: int
    outline_available: bool = False
    embeddings_available: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ManagedDocumentVersionRead(BaseModel):
    id: UUID
    document_id: UUID
    version_number: int
    status: str
    change_summary: str
    review_comment: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    created_by_name: str
    submitted_by_name: str | None = None
    reviewed_by_name: str | None = None
    original_filename: str
    processing_status: str


class ManagedDocumentListItem(BaseModel):
    id: UUID
    title: str
    description: str
    status: str
    owner_name: str
    checked_out_by_name: str | None = None
    checked_out_at: datetime | None = None
    version_count: int
    created_at: datetime
    updated_at: datetime
    current_version: ManagedDocumentVersionRead | None = None


class ManagedDocumentRead(ManagedDocumentListItem):
    owner_id: UUID
    checked_out_by_id: UUID | None = None
    current_document: DocumentRead | None = None
    versions: list[ManagedDocumentVersionRead]


class ManagedDocumentCreateResponse(BaseModel):
    id: UUID
    title: str
    status: str
    current_version: ManagedDocumentVersionRead | None = None


class ReviewActionRequest(BaseModel):
    comment: str = ""


class DocumentRead(BaseModel):
    id: UUID
    original_filename: str
    storage_path: str
    status: str
    page_count: int
    outline_available: bool = False
    embeddings_available: bool = False
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    pages: list[DocumentPageRead]
    sections: list[DocumentSectionRead]
    images: list[DocumentImageRead]
    outline_check: OutlineCheckResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class SectionSearchRequest(BaseModel):
    query: str
    limit: int = 10
    document_id: UUID | None = None


class SectionSearchResult(BaseModel):
    section_id: UUID
    document_id: UUID
    document_filename: str
    heading: str
    normalized_heading: str
    summary: str | None
    snippet: str
    start_page: int
    end_page: int
    score: float


class SectionSearchResponse(BaseModel):
    query: str
    results: list[SectionSearchResult]


class TemplateQuestionCheckRead(BaseModel):
    question: str
    status: str
    evidence: str = ""


class TemplateSectionRead(BaseModel):
    id: UUID
    sort_index: int
    key: str | None
    heading: str
    normalized_heading: str
    level: int
    requirement_summary: str
    questions: list[str]
    source_text: str

    model_config = ConfigDict(from_attributes=True)


class TemplateListItem(BaseModel):
    id: UUID
    original_filename: str
    display_name: str
    status: str
    section_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TemplateRead(BaseModel):
    id: UUID
    original_filename: str
    display_name: str
    storage_path: str
    status: str
    section_count: int
    created_at: datetime
    updated_at: datetime
    sections: list[TemplateSectionRead]

    model_config = ConfigDict(from_attributes=True)


class TemplateSectionCheckRead(BaseModel):
    id: UUID
    sort_index: int
    template_heading: str
    document_heading: str | None
    is_present: bool
    coverage_status: str
    confidence: float
    reasoning: str
    missing_topics: list[str]
    answered_questions: list[TemplateQuestionCheckRead]

    model_config = ConfigDict(from_attributes=True)


class TemplateSectionMatchRead(BaseModel):
    template_section_id: UUID
    template_heading: str
    template_level: int
    matched_document_section_id: UUID | None
    matched_document_heading: str | None
    matched_start_page: int | None
    matched_end_page: int | None
    match_score: float
    is_match: bool


class TemplateCheckRead(BaseModel):
    id: UUID
    template_id: UUID
    document_id: UUID
    status: str
    matched_section_count: int
    required_section_count: int
    result_storage_path: str | None
    summary: str | None
    extra_metadata: dict = {}
    created_at: datetime
    updated_at: datetime
    section_checks: list[TemplateSectionCheckRead]

    model_config = ConfigDict(from_attributes=True)


class TemplateCheckRequest(BaseModel):
    template_section_ids: list[UUID] | None = None


class StructureMappingItemRead(BaseModel):
    template_section_id: UUID
    template_heading: str
    template_level: int
    matched_document_section_id: UUID | None
    matched_document_heading: str | None
    matched_start_page: int | None
    matched_end_page: int | None
    confidence: float
    reasoning: str


class StructureMappingResponse(BaseModel):
    template_id: UUID
    document_id: UUID
    items: list[StructureMappingItemRead]
