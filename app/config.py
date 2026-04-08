from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    database_url: str = Field(alias="DATABASE_URL")
    openai_api_key: str = Field(alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")
    openai_embedding_model: str = Field(default="text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL")
    embedding_dimensions: int = Field(default=1536, alias="EMBEDDING_DIMENSIONS")
    port: int = Field(default=8000, alias="PORT")
    cors_origin: str = Field(default="*", alias="CORS_ORIGIN")
    jwt_secret: str | None = Field(default=None, alias="JWT_SECRET")
    auth_mode: str = Field(default="local", alias="AUTH_MODE")
    session_hours: int = Field(default=12, alias="SESSION_HOURS")
    bootstrap_admin_username: str = Field(default="admin", alias="BOOTSTRAP_ADMIN_USERNAME")
    bootstrap_admin_password: str = Field(default="admin", alias="BOOTSTRAP_ADMIN_PASSWORD")
    bootstrap_admin_display_name: str = Field(default="Administrator", alias="BOOTSTRAP_ADMIN_DISPLAY_NAME")
    ldap_server_uri: str | None = Field(default=None, alias="LDAP_SERVER_URI")
    ldap_use_ssl: bool = Field(default=False, alias="LDAP_USE_SSL")
    ldap_bind_dn: str | None = Field(default=None, alias="LDAP_BIND_DN")
    ldap_bind_password: str | None = Field(default=None, alias="LDAP_BIND_PASSWORD")
    ldap_base_dn: str | None = Field(default=None, alias="LDAP_BASE_DN")
    ldap_user_filter: str = Field(default="(sAMAccountName={username})", alias="LDAP_USER_FILTER")
    ldap_domain: str | None = Field(default=None, alias="LDAP_DOMAIN")
    ldap_default_role: str = Field(default="editor", alias="LDAP_DEFAULT_ROLE")
    base_dir: Path = BASE_DIR
    storage_root: Path = BASE_DIR / "storage"
    originals_dir: Path = BASE_DIR / "storage" / "originals"
    images_dir: Path = BASE_DIR / "storage" / "images"
    sanitized_dir: Path = BASE_DIR / "storage" / "sanitized"
    outline_results_dir: Path = BASE_DIR / "storage" / "outline-results"
    templates_dir: Path = BASE_DIR / "storage" / "templates"
    template_check_results_dir: Path = BASE_DIR / "storage" / "template-check-results"
    heading_min_font_size: float = 12.0
    heading_font_ratio: float = 0.92
    section_excerpt_chars: int = 12000
    pages_per_fallback_section: int = 20
    openai_timeout_seconds: int = 180

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
