from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import secrets
from typing import Any

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import AuthSession, User

try:
    from ldap3 import ALL, Connection, Server
    from ldap3.utils.conv import escape_filter_chars
except Exception:  # pragma: no cover
    Connection = None
    Server = None
    escape_filter_chars = None
    ALL = None


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def ensure_bootstrap_user(self, db: Session) -> None:
        username = self.settings.bootstrap_admin_username.strip()
        password = self.settings.bootstrap_admin_password
        if not username or not password:
            return
        existing = db.scalar(select(User).where(User.username == username))
        if existing is not None:
            return
        salt, password_hash = self.hash_password(password)
        user = User(
            username=username,
            display_name=self.settings.bootstrap_admin_display_name.strip() or username,
            role="admin",
            roles=["admin", "reviewer", "creator"],
            auth_provider="local",
            password_salt=salt,
            password_hash=password_hash,
            is_active=True,
        )
        db.add(user)
        db.commit()

    def register_local_user(
        self,
        db: Session,
        *,
        username: str,
        password: str,
        display_name: str,
        email: str | None = None,
    ) -> tuple[User, str, datetime]:
        normalized_username = username.strip()
        if not normalized_username or not password or not display_name.strip():
            raise HTTPException(status_code=400, detail="Benutzername, Anzeigename und Passwort sind erforderlich")
        if db.scalar(select(User).where(User.username == normalized_username)) is not None:
            raise HTTPException(status_code=409, detail="Benutzername ist bereits vergeben")

        salt, password_hash = self.hash_password(password)
        user = User(
            username=normalized_username,
            display_name=display_name.strip(),
            email=(email or "").strip() or None,
            role="creator",
            roles=["creator"],
            auth_provider="local",
            password_salt=salt,
            password_hash=password_hash,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return self._create_session(db, user)

    def authenticate(self, db: Session, username: str, password: str) -> tuple[User, str, datetime]:
        normalized_username = username.strip()
        if not normalized_username or not password:
            raise HTTPException(status_code=401, detail="Benutzername und Passwort sind erforderlich")

        modes = self.available_auth_modes()
        user: User | None = None
        if "local" in modes:
            user = self._authenticate_local(db, normalized_username, password)
        if user is None and "ldap" in modes:
            user = self._authenticate_ldap(db, normalized_username, password)
        if user is None:
            raise HTTPException(status_code=401, detail="Anmeldung fehlgeschlagen")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Benutzerkonto ist deaktiviert")

        self._sync_user_role(user)
        db.add(user)
        db.commit()
        db.refresh(user)
        return self._create_session(db, user)

    def logout(self, db: Session, token: str) -> None:
        token_hash = self._hash_token(token)
        session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
        if session is None:
            return
        db.delete(session)
        db.commit()

    def require_user(
        self,
        authorization: str | None = Header(default=None),
        db: Session = Depends(get_db),
    ) -> User:
        token = self._extract_bearer_token(authorization)
        if token is None:
            raise HTTPException(status_code=401, detail="Anmeldung erforderlich")

        session = db.scalar(
            select(AuthSession)
            .where(AuthSession.token_hash == self._hash_token(token))
            .join(AuthSession.user)
        )
        if session is None or session.user is None:
            raise HTTPException(status_code=401, detail="Sitzung ungültig")
        if session.expires_at <= datetime.now(UTC):
            db.delete(session)
            db.commit()
            raise HTTPException(status_code=401, detail="Sitzung abgelaufen")
        if not session.user.is_active:
            raise HTTPException(status_code=403, detail="Benutzerkonto ist deaktiviert")

        session.last_seen_at = datetime.now(UTC)
        db.add(session)
        db.commit()
        db.refresh(session.user)
        return session.user

    def available_auth_modes(self) -> list[str]:
        mode = self.settings.auth_mode.strip().lower()
        if mode == "ldap":
            return ["ldap"]
        if mode == "mixed":
            return ["local", "ldap"]
        return ["local"]

    def list_users(self, db: Session) -> list[User]:
        users = list(db.scalars(select(User).order_by(User.display_name.asc(), User.username.asc())).all())
        for user in users:
            self._sync_user_role(user)
        db.commit()
        return users

    def update_user(
        self,
        db: Session,
        user_id,
        *,
        display_name: str,
        email: str | None,
        roles: list[str],
        is_active: bool,
    ) -> User:
        user = db.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
        normalized_roles = self._normalize_roles(roles)
        if not normalized_roles:
            raise HTTPException(status_code=400, detail="Mindestens eine Rolle ist erforderlich")
        user.display_name = display_name.strip() or user.username
        user.email = (email or "").strip() or None
        user.roles = normalized_roles
        user.role = self._primary_role(normalized_roles)
        user.is_active = is_active
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def has_role(self, user: User, *roles: str) -> bool:
        assigned = set(self._normalize_roles(user.roles or [user.role]))
        return any(role in assigned for role in roles)

    def hash_password(self, password: str) -> tuple[str, str]:
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
        return base64.b64encode(salt).decode("ascii"), base64.b64encode(digest).decode("ascii")

    def verify_password(self, password: str, salt: str, password_hash: str) -> bool:
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            base64.b64decode(salt.encode("ascii")),
            310_000,
        )
        expected = base64.b64decode(password_hash.encode("ascii"))
        return hmac.compare_digest(digest, expected)

    def _authenticate_local(self, db: Session, username: str, password: str) -> User | None:
        user = db.scalar(select(User).where(User.username == username, User.auth_provider == "local"))
        if user is None or not user.password_salt or not user.password_hash:
            return None
        if not self.verify_password(password, user.password_salt, user.password_hash):
            return None
        return user

    def _authenticate_ldap(self, db: Session, username: str, password: str) -> User | None:
        if Connection is None or Server is None:
            return None
        if not self.settings.ldap_server_uri:
            return None

        display_name = username
        email: str | None = None
        bind_identity = username
        if self.settings.ldap_domain and "@" not in bind_identity:
            bind_identity = f"{username}@{self.settings.ldap_domain}"

        try:
            server = Server(self.settings.ldap_server_uri, use_ssl=self.settings.ldap_use_ssl, get_info=ALL)
            if self.settings.ldap_bind_dn and self.settings.ldap_bind_password and self.settings.ldap_base_dn and escape_filter_chars:
                with Connection(
                    server,
                    user=self.settings.ldap_bind_dn,
                    password=self.settings.ldap_bind_password,
                    auto_bind=True,
                ) as service_connection:
                    search_filter = self.settings.ldap_user_filter.format(username=escape_filter_chars(username))
                    service_connection.search(
                        search_base=self.settings.ldap_base_dn,
                        search_filter=search_filter,
                        attributes=["displayName", "mail", "userPrincipalName", "sAMAccountName"],
                    )
                    if not service_connection.entries:
                        return None
                    entry = service_connection.entries[0]
                    bind_identity = str(entry.entry_dn)
                    display_name = str(getattr(entry, "displayName", username) or username)
                    email = str(getattr(entry, "mail", "") or "") or None

            with Connection(server, user=bind_identity, password=password, auto_bind=True):
                pass
        except Exception:
            return None

        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            user = User(
                username=username,
                display_name=display_name,
                email=email,
                role=self._primary_role([self.settings.ldap_default_role]),
                roles=self._normalize_roles([self.settings.ldap_default_role]),
                auth_provider="ldap",
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return user

        user.display_name = display_name
        user.email = email
        user.auth_provider = "ldap"
        user.is_active = True
        user.roles = self._normalize_roles(user.roles or [self.settings.ldap_default_role])
        user.role = self._primary_role(user.roles)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def _extract_bearer_token(self, authorization: str | None) -> str | None:
        if not authorization:
            return None
        prefix = "bearer "
        if not authorization.lower().startswith(prefix):
            return None
        return authorization[len(prefix):].strip()

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _create_session(self, db: Session, user: User) -> tuple[User, str, datetime]:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(hours=self.settings.session_hours)
        session = AuthSession(
            user_id=user.id,
            token_hash=self._hash_token(token),
            expires_at=expires_at,
            last_seen_at=datetime.now(UTC),
        )
        db.add(session)
        db.commit()
        db.refresh(user)
        return user, token, expires_at

    def _normalize_roles(self, roles: list[str]) -> list[str]:
        aliases = {"ersteller": "creator", "prüfer": "reviewer", "pruefer": "reviewer", "administrator": "admin", "editor": "creator"}
        normalized: list[str] = []
        for role in roles:
            value = aliases.get((role or "").strip().lower(), (role or "").strip().lower())
            if value in {"creator", "reviewer", "admin"} and value not in normalized:
                normalized.append(value)
        if not normalized:
            normalized.append("creator")
        return normalized

    def _primary_role(self, roles: list[str]) -> str:
        normalized = self._normalize_roles(roles)
        if "admin" in normalized:
            return "admin"
        if "reviewer" in normalized:
            return "reviewer"
        return "creator"

    def _sync_user_role(self, user: User) -> None:
        user.roles = self._normalize_roles(user.roles or [user.role])
        user.role = self._primary_role(user.roles)


def build_auth_response(user: User, token: str, settings: Settings) -> dict[str, Any]:
    return {
        "token": token,
        "expires_at": datetime.now(UTC) + timedelta(hours=settings.session_hours),
        "user": user,
        "available_auth_modes": AuthService(settings).available_auth_modes(),
    }


auth_service = AuthService(get_settings())


def require_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    return auth_service.require_user(authorization=authorization, db=db)


def require_reviewer_user(user: User = Depends(require_current_user)) -> User:
    if not auth_service.has_role(user, "reviewer", "admin"):
        raise HTTPException(status_code=403, detail="Reviewer- oder Admin-Rechte erforderlich")
    return user


def require_admin_user(user: User = Depends(require_current_user)) -> User:
    if not auth_service.has_role(user, "admin"):
        raise HTTPException(status_code=403, detail="Admin-Rechte erforderlich")
    return user
