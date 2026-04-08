from __future__ import annotations

import argparse
import sys
from uuid import uuid4

import requests


def require_ok(response: requests.Response, label: str) -> dict:
    if not response.ok:
        raise SystemExit(f"{label} fehlgeschlagen: {response.status_code} {response.text}")
    if "application/json" not in response.headers.get("content-type", ""):
        raise SystemExit(f"{label} lieferte keine JSON-Antwort.")
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-Test fuer Registrierung, Auto-Login und Admin-Rollenpflege.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Basis-URL der laufenden Dokumat-App")
    parser.add_argument("--admin-username", default="admin", help="Admin-Benutzername")
    parser.add_argument("--admin-password", default="admin", help="Admin-Passwort")
    args = parser.parse_args()

    session = requests.Session()
    username = f"smoke_{uuid4().hex[:8]}"
    password = "Secret123!"
    email = f"{username}@example.org"

    register = require_ok(
        session.post(
            f"{args.base_url}/auth/register",
            json={
                "username": username,
                "password": password,
                "display_name": "Smoke Test User",
                "email": email,
            },
            timeout=15,
        ),
        "Registrierung",
    )
    user_token = register["token"]
    user = register["user"]
    if user["username"] != username or user.get("roles") != ["creator"]:
        raise SystemExit(f"Unerwartete Registrierungsantwort: {user}")

    me = require_ok(
        session.get(
            f"{args.base_url}/auth/me",
            headers={"Authorization": f"Bearer {user_token}"},
            timeout=15,
        ),
        "Profilabruf",
    )
    if me["username"] != username:
        raise SystemExit(f"Falscher Benutzer in /auth/me: {me}")

    forbidden = session.get(
        f"{args.base_url}/admin/users",
        headers={"Authorization": f"Bearer {user_token}"},
        timeout=15,
    )
    if forbidden.status_code != 403:
        raise SystemExit(f"Admin-Endpunkt sollte fuer normalen Benutzer 403 liefern, bekam aber {forbidden.status_code}")

    admin_login = require_ok(
        session.post(
            f"{args.base_url}/auth/login",
            json={"username": args.admin_username, "password": args.admin_password},
            timeout=15,
        ),
        "Admin-Login",
    )
    admin_token = admin_login["token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    users = require_ok(session.get(f"{args.base_url}/admin/users", headers=admin_headers, timeout=15), "Benutzerliste")
    created_user = next((item for item in users if item["username"] == username), None)
    if not created_user:
        raise SystemExit("Neu registrierter Benutzer wurde in der Admin-Liste nicht gefunden.")

    updated = require_ok(
        session.put(
            f"{args.base_url}/admin/users/{created_user['id']}",
            headers=admin_headers,
            json={
                "display_name": "Smoke Test User Updated",
                "email": email,
                "roles": ["creator", "reviewer"],
                "is_active": True,
            },
            timeout=15,
        ),
        "Rollenupdate",
    )
    if set(updated.get("roles") or []) != {"creator", "reviewer"}:
        raise SystemExit(f"Rollenupdate nicht uebernommen: {updated}")

    relogin = require_ok(
        session.post(
            f"{args.base_url}/auth/login",
            json={"username": username, "password": password},
            timeout=15,
        ),
        "Re-Login",
    )
    if set(relogin["user"].get("roles") or []) != {"creator", "reviewer"}:
        raise SystemExit(f"Neue Rollen nicht im Login sichtbar: {relogin['user']}")

    print("smoke-test-ok")
    print(f"Benutzer: {username}")
    print(f"Rollen: {', '.join(relogin['user']['roles'])}")
    print("Geprueft: Registrierung, Auto-Login, /auth/me, Admin-Schutz, Rollenupdate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
