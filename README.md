# Dokumat

`Dokumat` ist eine FastAPI-Anwendung zur technischen PDF-Verarbeitung und einfachen Dokumentenlenkung. Die App zerlegt PDFs lokal, extrahiert Text und Bilder, strukturiert Abschnitte mit OpenAI und ergänzt darauf einen fachlichen Workflow mit Anmeldung, Versionierung, Check-in/Check-out sowie Review- und Freigabestatus.

## Funktionen

- PDF-Upload und Import vorhandener Beispiel-PDFs
- lokale Extraktion von Seiten, Text, Bildern und Heading-Kandidaten
- OpenAI-gestuetzte Abschnittsstrukturierung und Gliederungspruefung
- verwaltete Dokumente mit Versionen und Status
- Anmeldung lokal oder optional ueber LDAP / Active Directory
- Rollenmodell mit `creator`, `reviewer` und `admin`
- Admin-Bereich fuer Benutzerverwaltung und Mehrfachrollen
- semantische Suche mit optionalem `pgvector`

## Tech-Stack

- FastAPI
- SQLAlchemy
- PostgreSQL
- OpenAI API
- PyMuPDF
- Vanilla HTML, CSS und JavaScript

## Schnellstart

### 1. Umgebung anlegen

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

### 2. `.env` anpassen

Mindestens diese Werte muessen gesetzt werden:

- `DATABASE_URL`
- `OPENAI_API_KEY`

Fuer den lokalen MVP reichen die Default-Werte fuer Authentifizierung und Admin-Benutzer in der Regel aus.

### 3. App starten

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Danach ist die Anwendung unter `http://localhost:8000/` erreichbar.

## Login und Rollen

Beim Aufruf der Startseite erscheint zuerst die Login-Maske. Die eigentliche Anwendung wird erst nach erfolgreicher Anmeldung sichtbar.

Im MVP gibt es drei Rollen:

- `creator` fuer Ersteller
- `reviewer` fuer Pruefer
- `admin` fuer Administratoren

Ein Benutzer kann mehrere Rollen gleichzeitig haben. Neue lokale Benutzer werden ueber die Registrierung direkt angemeldet. Eine E-Mail-Bestaetigung gibt es im MVP noch nicht.

Standardmaessig wird beim Start ein lokaler Admin angelegt, falls noch keiner existiert:

- Benutzername: `admin`
- Passwort: `admin`

Diese Werte sollten fuer echte Nutzung in `.env` ueberschrieben werden.

## Wichtige Umgebungsvariablen

Die Konfiguration wird aus `.env` geladen. Eine Vorlage liegt in [.env.example](./.env.example).

Wichtige Schluessel:

- `DATABASE_URL`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_EMBEDDING_MODEL`
- `EMBEDDING_DIMENSIONS`
- `PORT`
- `CORS_ORIGIN`
- `JWT_SECRET`
- `AUTH_MODE`
- `SESSION_HOURS`
- `BOOTSTRAP_ADMIN_USERNAME`
- `BOOTSTRAP_ADMIN_PASSWORD`
- `BOOTSTRAP_ADMIN_DISPLAY_NAME`
- `LDAP_SERVER_URI`
- `LDAP_USE_SSL`
- `LDAP_BIND_DN`
- `LDAP_BIND_PASSWORD`
- `LDAP_BASE_DN`
- `LDAP_USER_FILTER`
- `LDAP_DOMAIN`
- `LDAP_DEFAULT_ROLE`

## API-Beispiele

### Login

```powershell
curl -X POST http://localhost:8000/auth/login ^
  -H "Content-Type: application/json" ^
  -d "{\"username\":\"admin\",\"password\":\"admin\"}"
```

### Registrierung

```powershell
curl -X POST http://localhost:8000/auth/register ^
  -H "Content-Type: application/json" ^
  -d "{\"username\":\"max\",\"password\":\"secret123\",\"display_name\":\"Max Mustermann\",\"email\":\"max@example.org\"}"
```

### Verwaltetes Dokument anlegen

```powershell
curl -X POST http://localhost:8000/managed-documents/upload ^
  -H "Authorization: Bearer <token>" ^
  -F "title=Fachkonzept CRM" ^
  -F "description=Erste fachliche Fassung" ^
  -F "change_summary=Initiale Version" ^
  -F "file=@mein-dokument.pdf"
```

## Smoke-Test

Wenn die App laeuft, kannst du Registrierung, Auto-Login und Rollenverwaltung mit dem Smoke-Test pruefen:

```powershell
.\.venv\Scripts\python scripts\smoke_auth_flow.py --base-url http://127.0.0.1:8000
```

## Projektstruktur

- `app/` API, Modelle, Services und Datenbanklogik
- `frontend/` HTML, CSS und JavaScript der Weboberflaeche
- `scripts/` kleine Hilfs- und Smoke-Tests
- `storage/` lokale Dateispeicherung waehrend des Betriebs, nicht versioniert

## Hinweise

- Upload, Reprocessing, Analyse und Template-Verarbeitung laufen aktuell synchron im jeweiligen HTTP-Request.
- Fuer semantische Suche mit `pgvector` muss die PostgreSQL-Erweiterung `vector` verfuegbar sein.
- `storage/`, `.env`, PDFs, ZIPs, EXEs und lokale Outputs sind per `.gitignore` vom Repository ausgeschlossen.

## CI

Unter `.github/workflows/ci.yml` liegt ein einfacher GitHub-Workflow fuer:

- Python-Syntax-Compile der Backend-Dateien
- JavaScript-Syntaxcheck fuer `frontend/app.js`
