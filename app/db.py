from collections.abc import Generator
from importlib.util import find_spec

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


settings = get_settings()
pgvector_enabled = False


def _normalize_database_url(database_url: str) -> tuple[str | URL, dict]:
    normalized_url = database_url
    prefer_psycopg = find_spec("psycopg") is not None

    if prefer_psycopg and normalized_url.startswith("postgresql://"):
        normalized_url = normalized_url.replace("postgresql://", "postgresql+psycopg://", 1)
    elif prefer_psycopg and normalized_url.startswith("postgres://"):
        normalized_url = normalized_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif normalized_url.startswith("postgres://"):
        normalized_url = normalized_url.replace("postgres://", "postgresql://", 1)

    url = make_url(normalized_url)
    connect_args: dict[str, str] = {}
    schema = url.query.get("schema")
    if schema:
        connect_args["options"] = f"-c search_path={schema}"
        cleaned_query = {key: value for key, value in url.query.items() if key != "schema"}
        url = url.set(query=cleaned_query)

    return url, connect_args


class Base(DeclarativeBase):
    pass


database_url, connect_args = _normalize_database_url(settings.database_url)
engine = create_engine(database_url, future=True, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    global pgvector_enabled
    pgvector_enabled = _ensure_pgvector_extension()
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_document_section_columns()
    _ensure_user_columns()


def _ensure_pgvector_extension() -> bool:
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        return True
    except Exception:
        return False


def is_pgvector_enabled() -> bool:
    return pgvector_enabled


def _ensure_document_section_columns() -> None:
    inspector = inspect(engine)
    if "document_sections" not in inspector.get_table_names():
        return

    migration_statements: list[str] = []

    migration_statements.append("ALTER TABLE document_sections ADD COLUMN IF NOT EXISTS raw_text_exact TEXT")
    migration_statements.append("ALTER TABLE document_sections ADD COLUMN IF NOT EXISTS cleaned_text TEXT")
    migration_statements.append("ALTER TABLE document_sections ADD COLUMN IF NOT EXISTS markdown_text TEXT")
    if pgvector_enabled:
        migration_statements.append(
            f"ALTER TABLE document_sections ADD COLUMN IF NOT EXISTS embedding vector({settings.embedding_dimensions})"
        )
    migration_statements.append(
        "CREATE INDEX IF NOT EXISTS document_sections_search_idx "
        "ON document_sections USING GIN (to_tsvector('simple', "
        "coalesce(normalized_heading, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(cleaned_text, '')))"
    )

    backfill_statements = [
        "UPDATE document_sections SET raw_text_exact = COALESCE(raw_text_exact, raw_text, '') WHERE raw_text_exact IS NULL",
        "UPDATE document_sections SET cleaned_text = COALESCE(cleaned_text, raw_text, '') WHERE cleaned_text IS NULL",
        "UPDATE document_sections SET markdown_text = COALESCE(markdown_text, content_markdown, raw_text, '') WHERE markdown_text IS NULL",
        "ALTER TABLE document_sections ALTER COLUMN raw_text_exact SET DEFAULT ''",
        "ALTER TABLE document_sections ALTER COLUMN cleaned_text SET DEFAULT ''",
        "ALTER TABLE document_sections ALTER COLUMN markdown_text SET DEFAULT ''",
        "UPDATE document_sections SET raw_text_exact = '' WHERE raw_text_exact IS NULL",
        "UPDATE document_sections SET cleaned_text = '' WHERE cleaned_text IS NULL",
        "UPDATE document_sections SET markdown_text = '' WHERE markdown_text IS NULL",
        "ALTER TABLE document_sections ALTER COLUMN raw_text_exact SET NOT NULL",
        "ALTER TABLE document_sections ALTER COLUMN cleaned_text SET NOT NULL",
        "ALTER TABLE document_sections ALTER COLUMN markdown_text SET NOT NULL",
    ]

    with engine.begin() as connection:
        for statement in migration_statements + backfill_statements:
            connection.execute(text(statement))


def _ensure_user_columns() -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    statements = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS roles JSONB",
        "UPDATE users SET roles = CASE "
        "WHEN role = 'admin' THEN '[\"admin\", \"reviewer\", \"creator\"]'::jsonb "
        "WHEN role = 'reviewer' THEN '[\"reviewer\"]'::jsonb "
        "WHEN role = 'creator' THEN '[\"creator\"]'::jsonb "
        "WHEN role = 'editor' THEN '[\"creator\"]'::jsonb "
        "ELSE '[\"creator\"]'::jsonb END "
        "WHERE roles IS NULL OR jsonb_typeof(roles) <> 'array' OR jsonb_array_length(roles) = 0",
        "ALTER TABLE users ALTER COLUMN roles SET DEFAULT '[]'::jsonb",
        "UPDATE users SET roles = '[\"creator\"]'::jsonb WHERE roles IS NULL",
        "ALTER TABLE users ALTER COLUMN roles SET NOT NULL",
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
