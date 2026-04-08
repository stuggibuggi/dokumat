from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.db import Base


settings = get_settings()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    email: Mapped[str | None] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(32), default="editor", nullable=False)
    roles: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    auth_provider: Mapped[str] = mapped_column(String(32), default="local", nullable=False)
    password_salt: Mapped[str | None] = mapped_column(String(128))
    password_hash: Mapped[str | None] = mapped_column(String(256))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    extra_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    sessions: Mapped[list[AuthSession]] = relationship(back_populates="user", cascade="all, delete-orphan")
    owned_documents: Mapped[list[ManagedDocument]] = relationship(
        back_populates="owner",
        foreign_keys="ManagedDocument.owner_id",
    )
    checked_out_documents: Mapped[list[ManagedDocument]] = relationship(
        back_populates="checked_out_by",
        foreign_keys="ManagedDocument.checked_out_by_id",
    )
    created_versions: Mapped[list[ManagedDocumentVersion]] = relationship(
        back_populates="created_by",
        foreign_keys="ManagedDocumentVersion.created_by_id",
    )
    submitted_versions: Mapped[list[ManagedDocumentVersion]] = relationship(
        back_populates="submitted_by",
        foreign_keys="ManagedDocumentVersion.submitted_by_id",
    )
    reviewed_versions: Mapped[list[ManagedDocumentVersion]] = relationship(
        back_populates="reviewed_by",
        foreign_keys="ManagedDocumentVersion.reviewed_by_id",
    )


class AuthSession(TimestampMixin, Base):
    __tablename__ = "auth_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="sessions")


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    extra_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    pages: Mapped[list[DocumentPage]] = relationship(back_populates="document", cascade="all, delete-orphan")
    sections: Mapped[list[DocumentSection]] = relationship(back_populates="document", cascade="all, delete-orphan")
    images: Mapped[list[DocumentImage]] = relationship(back_populates="document", cascade="all, delete-orphan")
    template_checks: Mapped[list[TemplateCheck]] = relationship(back_populates="document", cascade="all, delete-orphan")
    managed_versions: Mapped[list[ManagedDocumentVersion]] = relationship(back_populates="document")


class ManagedDocument(TimestampMixin, Base):
    __tablename__ = "managed_documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    current_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("managed_document_versions.id", ondelete="SET NULL"))
    checked_out_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    checked_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extra_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    owner: Mapped[User] = relationship(back_populates="owned_documents", foreign_keys=[owner_id])
    checked_out_by: Mapped[User | None] = relationship(back_populates="checked_out_documents", foreign_keys=[checked_out_by_id])
    current_version: Mapped[ManagedDocumentVersion | None] = relationship(
        foreign_keys=[current_version_id],
        post_update=True,
    )
    versions: Mapped[list[ManagedDocumentVersion]] = relationship(
        back_populates="managed_document",
        cascade="all, delete-orphan",
        foreign_keys="ManagedDocumentVersion.managed_document_id",
        order_by="ManagedDocumentVersion.version_number.desc()",
    )


class ManagedDocumentVersion(TimestampMixin, Base):
    __tablename__ = "managed_document_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    managed_document_id: Mapped[UUID] = mapped_column(
        ForeignKey("managed_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    change_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    submitted_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[str | None] = mapped_column(Text)
    extra_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    managed_document: Mapped[ManagedDocument] = relationship(
        back_populates="versions",
        foreign_keys=[managed_document_id],
    )
    document: Mapped[Document] = relationship(back_populates="managed_versions")
    created_by: Mapped[User] = relationship(back_populates="created_versions", foreign_keys=[created_by_id])
    submitted_by: Mapped[User | None] = relationship(back_populates="submitted_versions", foreign_keys=[submitted_by_id])
    reviewed_by: Mapped[User | None] = relationship(back_populates="reviewed_versions", foreign_keys=[reviewed_by_id])


class DocumentPage(TimestampMixin, Base):
    __tablename__ = "document_pages"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text_content: Mapped[str] = mapped_column(Text, nullable=False)
    detected_headings: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)
    extra_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    document: Mapped[Document] = relationship(back_populates="pages")
    images: Mapped[list[DocumentImage]] = relationship(back_populates="page")


class DocumentSection(TimestampMixin, Base):
    __tablename__ = "document_sections"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False)
    heading: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_heading: Mapped[str] = mapped_column(String(512), nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    start_page: Mapped[int] = mapped_column(Integer, nullable=False)
    end_page: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text_exact: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cleaned_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    markdown_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    confidence: Mapped[float] = mapped_column(default=0.0, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dimensions))
    extra_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    document: Mapped[Document] = relationship(back_populates="sections")
    images: Mapped[list[DocumentImage]] = relationship(back_populates="section")


class DocumentImage(TimestampMixin, Base):
    __tablename__ = "document_images"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    page_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_pages.id", ondelete="SET NULL"))
    section_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_sections.id", ondelete="SET NULL"))
    image_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(128))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(128), nullable=False)
    extra_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    document: Mapped[Document] = relationship(back_populates="images")
    page: Mapped[DocumentPage | None] = relationship(back_populates="images")
    section: Mapped[DocumentSection | None] = relationship(back_populates="images")


class ReviewTemplate(TimestampMixin, Base):
    __tablename__ = "review_templates"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ready", nullable=False)
    section_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    extra_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    sections: Mapped[list[ReviewTemplateSection]] = relationship(back_populates="template", cascade="all, delete-orphan")
    checks: Mapped[list[TemplateCheck]] = relationship(back_populates="template", cascade="all, delete-orphan")


class ReviewTemplateSection(TimestampMixin, Base):
    __tablename__ = "review_template_sections"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    template_id: Mapped[UUID] = mapped_column(ForeignKey("review_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False)
    key: Mapped[str | None] = mapped_column(String(128))
    heading: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_heading: Mapped[str] = mapped_column(String(512), nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    requirement_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    questions: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extra_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    template: Mapped[ReviewTemplate] = relationship(back_populates="sections")
    section_checks: Mapped[list[TemplateSectionCheck]] = relationship(back_populates="template_section", cascade="all, delete-orphan")


class TemplateCheck(TimestampMixin, Base):
    __tablename__ = "template_checks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    template_id: Mapped[UUID] = mapped_column(ForeignKey("review_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False)
    matched_section_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    required_section_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result_storage_path: Mapped[str | None] = mapped_column(String(1024))
    summary: Mapped[str | None] = mapped_column(Text)
    extra_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    template: Mapped[ReviewTemplate] = relationship(back_populates="checks")
    document: Mapped[Document] = relationship(back_populates="template_checks")
    section_checks: Mapped[list[TemplateSectionCheck]] = relationship(back_populates="template_check", cascade="all, delete-orphan")


class TemplateSectionCheck(TimestampMixin, Base):
    __tablename__ = "template_section_checks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    template_check_id: Mapped[UUID] = mapped_column(ForeignKey("template_checks.id", ondelete="CASCADE"), nullable=False, index=True)
    template_section_id: Mapped[UUID] = mapped_column(
        ForeignKey("review_template_sections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_section_id: Mapped[UUID | None] = mapped_column(ForeignKey("document_sections.id", ondelete="SET NULL"))
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False)
    template_heading: Mapped[str] = mapped_column(String(512), nullable=False)
    document_heading: Mapped[str | None] = mapped_column(String(512))
    is_present: Mapped[bool] = mapped_column(nullable=False, default=False)
    coverage_status: Mapped[str] = mapped_column(String(32), nullable=False, default="missing")
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.0)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False, default="")
    missing_topics: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    answered_questions: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)
    extra_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    template_check: Mapped[TemplateCheck] = relationship(back_populates="section_checks")
    template_section: Mapped[ReviewTemplateSection] = relationship(back_populates="section_checks")
