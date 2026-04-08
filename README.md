# Dokumat

`Dokumat` ist eine FastAPI-Anwendung, die große PDF-Dokumente lokal zerlegt, Bilder extrahiert, Abschnitte mit Hilfe der OpenAI API strukturiert und alles in PostgreSQL speichert.
Zusätzlich enthält sie jetzt eine einfache Dokumentenlenkung mit Anmeldung, Versionierung, Check-in/Check-out sowie Genehmigungs- und Freigabestatus.

## Was die Anwendung macht

- lädt PDF-Dateien per API hoch oder importiert vorhandene Beispiel-PDFs aus dem Projektwurzelverzeichnis
- extrahiert seitenweise Text und eingebettete Bilder mit `PyMuPDF`
- erkennt Überschriften heuristisch und baut daraus Dokumentbereiche/Abschnitte
- normalisiert jeden Abschnitt über die OpenAI Responses API und speichert Überschrift, Zusammenfassung und Schlagwörter
- schreibt Dokumente, Seiten, Bilder und Abschnitte in PostgreSQL
- stellt Bilder unter `/storage/...` statisch bereit

## Projektstruktur

- `app/main.py` startet die API und die Routen
- `app/models.py` enthält das PostgreSQL-Datenmodell
- `app/services/pdf_extractor.py` extrahiert Text, Überschriften und Bilder
- `app/services/section_builder.py` baut Abschnitte aus den PDF-Seiten
- `app/services/openai_structurer.py` ruft die OpenAI API für die Abschnitts-Normalisierung auf
- `app/services/ingestion.py` orchestriert die Gesamtverarbeitung

## Voraussetzungen

- Python 3.13+
- erreichbare PostgreSQL-Datenbank
- gültiger `OPENAI_API_KEY` in `.env`

Deine vorhandene `.env` wird bereits berücksichtigt. Verwendet werden aktuell:

- `DATABASE_URL`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_EMBEDDING_MODEL`
- `EMBEDDING_DIMENSIONS`
- `PORT`
- `CORS_ORIGIN`
- `AUTH_MODE` (`local`, `ldap`, `mixed`)
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

Standardmäßig wird beim Start ein lokaler Admin angelegt, falls er noch nicht existiert:

- Benutzername: `admin`
- Passwort: `admin`

Für produktive Nutzung sollten diese Werte direkt über `.env` geändert werden.

Rollen im MVP:

- `creator` für Ersteller
- `reviewer` für Prüfer
- `admin` für Administratoren

Ein Benutzer kann mehrere Rollen gleichzeitig haben. Die Rollen werden im Admin-Bereich verwaltet.

Für semantische Suche mit `pgvector` muss die PostgreSQL-Erweiterung `vector` auf dem Datenbankserver installiert sein. Fehlt sie, startet die App weiter, aber Embeddings und semantische Suche bleiben deaktiviert.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Starten

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

Im Browser ist die Oberfläche danach unter `http://localhost:8000/` erreichbar.

Beim Aufruf der Startseite erscheint zuerst eine Login-Maske. Inhalte der Anwendung werden erst nach erfolgreicher Anmeldung angezeigt.

Wichtig: Starte die Anwendung bevorzugt mit dem Python aus `.venv`, damit die lokal installierten Pakete wie `psycopg` sicher verwendet werden und nicht ein globales `uvicorn` aus Anaconda einspringt.

Wenn du lieber den Port aus `.env` verwenden willst:

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --reload --port $env:PORT
```

## API-Endpunkte

### Anmeldung

```powershell
curl -X POST http://localhost:8000/auth/login ^
  -H "Content-Type: application/json" ^
  -d '{"username":"admin","password":"admin"}'
```

Die Antwort enthält ein Bearer-Token, das für die geschützten Endpunkte mitgeschickt werden muss.

### Registrierung

```powershell
curl -X POST http://localhost:8000/auth/register ^
  -H "Content-Type: application/json" ^
  -d '{"username":"max","password":"secret123","display_name":"Max Mustermann","email":"max@example.org"}'
```

Im aktuellen MVP wird der Benutzer nach erfolgreicher Registrierung sofort angemeldet. Eine E-Mail-Bestätigung gibt es noch nicht.

### Benutzerverwaltung

Administratoren sehen in der Oberfläche einen eigenen Bereich `Admin`. Dort können Benutzer:

- aktiviert oder deaktiviert werden
- Anzeigename und E-Mail gepflegt bekommen
- mit mehreren Rollen gleichzeitig versehen werden

Verfügbare Rollen:

- `creator` für Ersteller
- `reviewer` für Prüfer
- `admin` für Administratoren

Der initiale Bootstrap-Benutzer `admin` besitzt alle drei Rollen.

### Smoke-Test für Anmeldung und Rollen

Wenn die App bereits läuft, kannst du den MVP-Flow mit diesem Skript prüfen:

```powershell
.\.venv\Scripts\python scripts\smoke_auth_flow.py --base-url http://127.0.0.1:8000
```

Geprüft werden dabei:

- Registrierung mit sofortigem Auto-Login
- `/auth/me` mit dem neuen Token
- Schutz des Admin-Bereichs für normale Benutzer
- Rollenänderung durch den Admin
- erneuter Login mit den aktualisierten Rollen

### Verwaltetes Dokument anlegen

```powershell
curl -X POST http://localhost:8000/managed-documents/upload ^
  -H "Authorization: Bearer <token>" ^
  -F "title=Fachkonzept CRM" ^
  -F "description=Erste fachliche Fassung" ^
  -F "change_summary=Initiale Version" ^
  -F "file=@mein-dokument.pdf"
```

### Beispiel-PDF aus dem Root importieren

```powershell
curl -X POST http://localhost:8000/documents/import-example ^
  -H "Content-Type: application/json" ^
  -d '{"filename":"1773410013000-AWDPIT.pdf"}'
```

### PDF hochladen

```powershell
curl -X POST http://localhost:8000/documents/upload -F "file=@mein-dokument.pdf"
```

### Status und Ergebnis abfragen

```powershell
curl http://localhost:8000/documents
curl http://localhost:8000/documents/<document-id>
```

Alternativ kannst du Upload, Beispiel-Importe, Abschnitte und Bilder direkt über die Weboberfläche bedienen.
In der Abschnittsansicht kannst du zwischen `raw_text_exact`, `cleaned_text` und `markdown_text` umschalten.
Bestehende Importe lassen sich in der Weboberfläche über `Neu verarbeiten` erneut vollständig einlesen und strukturieren.

## Datenmodell

Die Anwendung enthält jetzt zusätzlich zur technischen PDF-Verarbeitung eine fachliche Dokumentenlenkung:

- `users` für lokale und per LDAP/AD synchronisierte Benutzer
- `auth_sessions` für angemeldete Sitzungen
- `managed_documents` für fachliche Dokumente mit Checkout-Status
- `managed_document_versions` für versionierte Stände inklusive Review-Status

Für die technische Verarbeitung werden weiterhin diese Tabellen genutzt:

- `documents` für den Importstatus des Gesamtdokuments
- `document_pages` für den seitenweise extrahierten Text und erkannte Überschriften
- `document_sections` für die extrahierten Bereiche mit Überschrift, OpenAI-Zusammenfassung und drei Textvarianten: `raw_text_exact`, `cleaned_text`, `markdown_text`
- `document_images` für extrahierte Bilder samt Dateipfad und Referenzen auf Seite und Abschnitt

## Dokumentenlenkung

Der neue Workflow läuft so:

- Benutzer melden sich lokal oder optional über LDAP/Active Directory an
- Ein Upload erzeugt ein fachliches Dokument mit Version 1
- Dokumente können ausgecheckt werden, damit eine Person exklusiv daran arbeitet
- Beim Einchecken wird eine neue Version angelegt und technisch neu verarbeitet
- Versionen können zur Prüfung eingereicht, genehmigt, abgelehnt und freigegeben werden
- Der Status ist in der Oberfläche direkt sichtbar

## Hinweise für sehr große PDFs

- Upload, Reprocessing, Analyse und Template-Verarbeitung laufen direkt im jeweiligen HTTP-Request und nicht als Hintergrundtask
- Bilder werden sofort lokal gespeichert, nicht als Blob in PostgreSQL
- die Abschnittsbildung ist hybrid: lokale PDF-Analyse für Skalierbarkeit, OpenAI für die Normalisierung
- wenn ein Dokument keine klaren Überschriften hat, werden Fallback-Abschnitte über Seitenfenster gebildet

## Nächste sinnvolle Ausbaustufen

- echte Job-Queue mit Redis/Celery oder Dramatiq für produktive Last
- OCR für gescannte PDFs ohne eingebetteten Text
- Embeddings oder Vektorsuche pro Abschnitt
- Frontend für Upload, Status und Vorschau
