from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import fitz
from openai import BadRequestError, OpenAI, RateLimitError

from app.config import Settings
from app.schemas import OutlineCheckResponse, OutlineChunkDebug, OutlineNode
from app.services.pdf_sanitizer import PDFSanitizer
from app.services.storage import StorageService


OUTLINE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "hierarchy": {
            "type": "array",
            "items": {"$ref": "#/$defs/node"},
        },
        "raw_outline_markdown": {"type": "string"},
    },
    "required": ["hierarchy", "raw_outline_markdown"],
    "$defs": {
        "node": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "heading": {"type": "string"},
                "level": {"type": "integer"},
                "children": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/node"},
                },
            },
            "required": ["heading", "level", "children"],
        }
    },
}


OUTLINE_PROMPT = """
Analysiere dieses Dokument und extrahiere ausschließlich die tatsächliche Hauptgliederung inklusive Hierarchie der Überschriften.

Arbeitsregeln:
- Nutze nur Überschriften, die im eigentlichen Dokumentkörper vorkommen.
- Ignoriere Inhaltsverzeichnis, Dot-Leader, reine Seitenzahlen, Kopf-/Fußzeilen, Datumszeilen, Bildplatzhalter und ähnliche Artefakte.
- Ignoriere Einträge, die nur im Inhaltsverzeichnis vorkommen, aber nicht als echte Abschnittsüberschrift im Dokument erscheinen.
- Bevorzuge die Gliederung ab dem eigentlichen Dokumentbeginn, nicht Verzeichnis- oder Vorspannseiten.
- Erkenne Hierarchie aus Nummerierungen wie 1, 1.1, 1.1.1 sowie aus klar erkennbaren Überschriftenebenen.
- Führe keine Abschnitte zusammen, die unterschiedliche Überschriften haben.
- Erfinde keine fehlenden Überschriften.
- Behalte die Überschrift möglichst nah am Dokumenttext bei, aber entferne offensichtliche Seitenzahlen oder Dot-Leader.
- Wenn dieselbe Überschrift mehrfach vorkommt, nimm sie nur einmal auf, sofern sie dieselbe Gliederungsposition beschreibt.

Ausgabeanforderungen:
- Gib die Hierarchie als Baum zurück.
- `level=1` ist die oberste relevante Dokumentebene.
- `children` enthält die direkten Unterpunkte.
- Erzeuge zusätzlich `raw_outline_markdown` als gut lesbare Markdown-Gliederung.
""".strip()

NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+)*[.)]?\s+\S+")
MAX_OUTLINE_INPUT_CHARS = 16000
MAX_OUTLINE_CANDIDATES = 500
CHUNK_PAGE_SIZE = 24
CHUNK_PAGE_OVERLAP = 3
DIRECT_PDF_PAGE_LIMIT = 24


@dataclass(slots=True)
class OutlineChunk:
    index: int
    start_page: int
    end_page: int
    text: str
    candidate_count: int


@dataclass(slots=True)
class FlatNode:
    heading: str
    level: int


class OutlineCheckService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key, timeout=settings.openai_timeout_seconds)
        self.sanitizer = PDFSanitizer()
        self.storage = StorageService(settings)

    def analyze_pdf(self, source_path: Path, original_filename: str) -> OutlineCheckResponse:
        self.storage.ensure_directories()
        sanitized_path = self.storage.create_sanitized_pdf_target(original_filename)
        sanitized_result = self.sanitizer.sanitize_images(source_path, sanitized_path)
        page_count = self._page_count(source_path)

        try:
            if page_count <= DIRECT_PDF_PAGE_LIMIT:
                payload = self._analyze_via_pdf(sanitized_result.sanitized_path)
                analysis_mode = "sanitized_pdf"
                chunk_count = 1
                chunk_debug: list[OutlineChunkDebug] = []
            else:
                payload, chunk_count, chunk_debug = self._analyze_via_chunked_text(source_path)
                analysis_mode = "chunked_text_merge"
        except (BadRequestError, RateLimitError):
            payload, chunk_count, chunk_debug = self._analyze_via_chunked_text(source_path)
            analysis_mode = "chunked_text_merge"

        result_path = self.storage.create_outline_json_target(original_filename)
        result_payload = {
            "filename": original_filename,
            "sanitized_filename": sanitized_result.sanitized_path.name,
            "sanitized_storage_path": self.storage.to_relative(sanitized_result.sanitized_path),
            "result_storage_path": self.storage.to_relative(result_path),
            "analysis_mode": analysis_mode,
            "chunk_count": chunk_count,
            "image_placeholders": sanitized_result.image_placeholders,
            "hierarchy": payload["hierarchy"],
            "raw_outline_markdown": payload["raw_outline_markdown"],
            "chunks": [chunk.model_dump(mode="json") for chunk in chunk_debug],
        }
        result_path.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return OutlineCheckResponse(
            filename=original_filename,
            sanitized_filename=sanitized_result.sanitized_path.name,
            sanitized_storage_path=self.storage.to_relative(sanitized_result.sanitized_path),
            result_storage_path=self.storage.to_relative(result_path),
            analysis_mode=analysis_mode,
            chunk_count=chunk_count,
            image_placeholders=sanitized_result.image_placeholders,
            hierarchy=[OutlineNode.model_validate(item) for item in payload["hierarchy"]],
            raw_outline_markdown=payload["raw_outline_markdown"],
            chunks=chunk_debug,
        )

    def load_result(self, result_storage_path: str) -> OutlineCheckResponse | None:
        if not result_storage_path:
            return None

        path = self.settings.base_dir / result_storage_path
        if not path.exists():
            return None

        payload = json.loads(path.read_text(encoding="utf-8"))
        return OutlineCheckResponse.model_validate(payload)

    def _page_count(self, source_path: Path) -> int:
        with fitz.open(source_path) as document:
            return document.page_count

    def _analyze_via_pdf(self, pdf_path: Path) -> dict:
        with pdf_path.open("rb") as file_handle:
            uploaded = self.client.files.create(
                file=file_handle,
                purpose="user_data",
            )

        try:
            response = self.client.responses.create(
                model=self.settings.openai_model,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_file", "file_id": uploaded.id},
                            {"type": "input_text", "text": OUTLINE_PROMPT},
                        ],
                    }
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "outline_check",
                        "schema": OUTLINE_SCHEMA,
                        "strict": True,
                    }
                },
            )
            return json.loads(response.output_text)
        finally:
            try:
                self.client.files.delete(uploaded.id)
            except Exception:
                pass

    def _analyze_via_chunked_text(self, source_path: Path) -> tuple[dict, int, list[OutlineChunkDebug]]:
        chunks = self._build_chunks(source_path)
        if not chunks:
            chunks = [
                OutlineChunk(
                    index=1,
                    start_page=1,
                    end_page=1,
                    text=self._extract_pdf_excerpt(source_path),
                    candidate_count=0,
                )
            ]

        merged_nodes: list[FlatNode] = []
        debug_chunks: list[OutlineChunkDebug] = []
        for chunk in chunks:
            payload = self._analyze_chunk(chunk)
            chunk_nodes = self._flatten_nodes(payload["hierarchy"])
            merged_nodes.extend(chunk_nodes)
            debug_chunks.append(
                OutlineChunkDebug(
                    chunk_index=chunk.index,
                    start_page=chunk.start_page,
                    end_page=chunk.end_page,
                    candidate_count=chunk.candidate_count,
                    hierarchy=[OutlineNode.model_validate(item) for item in payload["hierarchy"]],
                    raw_outline_markdown=payload["raw_outline_markdown"],
                )
            )

        merged_nodes = self._dedupe_flat_nodes(merged_nodes)
        hierarchy = self._build_tree(merged_nodes)
        return {
            "hierarchy": [self._node_to_dict(node) for node in hierarchy],
            "raw_outline_markdown": self._nodes_to_markdown(hierarchy),
        }, len(chunks), debug_chunks

    def _build_chunks(self, source_path: Path) -> list[OutlineChunk]:
        pages = self._extract_outline_candidates_by_page(source_path)
        if not pages:
            return []

        chunks: list[OutlineChunk] = []
        start_index = 0
        chunk_index = 1

        while start_index < len(pages):
            end_index = min(start_index + CHUNK_PAGE_SIZE, len(pages))
            chunk_pages = pages[start_index:end_index]
            chunk_text = self._render_chunk_text(chunk_pages)

            if len(chunk_text) > MAX_OUTLINE_INPUT_CHARS:
                trimmed_pages: list[tuple[int, list[str]]] = []
                current_length = 0
                for page_number, lines in chunk_pages:
                    page_block = self._render_chunk_text([(page_number, lines)])
                    if trimmed_pages and current_length + len(page_block) > MAX_OUTLINE_INPUT_CHARS:
                        break
                    trimmed_pages.append((page_number, lines))
                    current_length += len(page_block)
                chunk_pages = trimmed_pages or chunk_pages[:1]
                chunk_text = self._render_chunk_text(chunk_pages)

            chunks.append(
                OutlineChunk(
                    index=chunk_index,
                    start_page=chunk_pages[0][0],
                    end_page=chunk_pages[-1][0],
                    text=chunk_text[:MAX_OUTLINE_INPUT_CHARS],
                    candidate_count=sum(len(lines) for _, lines in chunk_pages),
                )
            )
            if end_index >= len(pages):
                break
            start_index = max(end_index - CHUNK_PAGE_OVERLAP, start_index + 1)
            chunk_index += 1

        return chunks

    def _extract_outline_candidates_by_page(self, source_path: Path) -> list[tuple[int, list[str]]]:
        pages: list[tuple[int, list[str]]] = []
        with fitz.open(source_path) as document:
            for page_number, page in enumerate(document, start=1):
                lines = [line.strip() for line in page.get_text("text").splitlines() if line.strip()]
                if not lines:
                    continue
                candidates = self._page_outline_candidates(lines)
                if candidates:
                    pages.append((page_number, candidates))
        return pages

    def _render_chunk_text(self, page_candidates: list[tuple[int, list[str]]]) -> str:
        result: list[str] = []
        seen: set[str] = set()
        candidate_count = 0

        for page_number, lines in page_candidates:
            page_lines: list[str] = []
            for line in lines:
                normalized = self._normalize_candidate(line)
                if normalized in seen:
                    continue
                seen.add(normalized)
                page_lines.append(line)
                candidate_count += 1
                if candidate_count >= MAX_OUTLINE_CANDIDATES:
                    break
            if page_lines:
                result.append(f"--- Seitenblock: Seite {page_number} ---")
                result.extend(page_lines)
            if candidate_count >= MAX_OUTLINE_CANDIDATES:
                break

        return "\n".join(result)

    def _analyze_chunk(self, chunk: OutlineChunk) -> dict:
        prompt = (
            f"{OUTLINE_PROMPT}\n\n"
            f"Dies ist Chunk {chunk.index} mit Seiten {chunk.start_page}-{chunk.end_page}.\n"
            "Nutze ausschließlich die folgenden lokal erkannten Überschriftenkandidaten und kurzen Kontextzeilen "
            "für diesen Seitenblock. Leite daraus die Gliederung dieses Teilausschnitts ab.\n\n"
            f"{chunk.text}"
        )
        response = self.client.responses.create(
            model=self.settings.openai_model,
            input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "outline_check",
                    "schema": OUTLINE_SCHEMA,
                    "strict": True,
                }
            },
        )
        return json.loads(response.output_text)

    def _page_outline_candidates(self, lines: list[str]) -> list[str]:
        candidates: list[str] = []
        for index, line in enumerate(lines):
            if not self._looks_like_outline_candidate(line):
                continue
            candidates.append(line)
            if index + 1 < len(lines):
                next_line = lines[index + 1]
                if len(next_line) <= 120 and not self._looks_like_noise(next_line):
                    candidates.append(f"  Kontext: {next_line}")
        return candidates

    def _looks_like_outline_candidate(self, line: str) -> bool:
        stripped = line.strip()
        if self._looks_like_noise(stripped):
            return False
        if NUMBERED_HEADING_RE.match(stripped):
            return True
        if len(stripped) > 120 or stripped.endswith("."):
            return False
        words = stripped.split()
        if not words or len(words) > 14:
            return False
        uppercase_ratio = self._uppercase_ratio(stripped)
        title_ratio = sum(1 for word in words if word[:1].isupper()) / len(words)
        return uppercase_ratio >= 0.45 or title_ratio >= 0.7

    def _looks_like_noise(self, line: str) -> bool:
        stripped = line.strip()
        if len(stripped) < 3 or len(stripped) > 180:
            return True
        if re.fullmatch(r"[\W_]+", stripped):
            return True
        if re.fullmatch(r"\d+", stripped):
            return True
        if "...." in stripped:
            return True
        if stripped.lower().endswith((".pdf", ".doc", ".docx", ".xlsx", ".xls", ".csv", ".xml")):
            return True
        return False

    def _normalize_candidate(self, line: str) -> str:
        return re.sub(r"\s+", " ", line.strip().lower())

    def _uppercase_ratio(self, value: str) -> float:
        letters = [character for character in value if character.isalpha()]
        if not letters:
            return 0.0
        uppercase = [character for character in letters if character.isupper()]
        return len(uppercase) / len(letters)

    def _extract_pdf_excerpt(self, source_path: Path) -> str:
        parts: list[str] = []
        total_chars = 0
        with fitz.open(source_path) as document:
            for page_number, page in enumerate(document, start=1):
                text = page.get_text("text").strip()
                if not text:
                    continue
                excerpt = text[:1500]
                chunk = f"--- Seite {page_number} ---\n{excerpt}"
                if total_chars + len(chunk) > MAX_OUTLINE_INPUT_CHARS:
                    break
                parts.append(chunk)
                total_chars += len(chunk)
        return "\n\n".join(parts)

    def _flatten_nodes(self, nodes: list[dict]) -> list[FlatNode]:
        result: list[FlatNode] = []
        for node in nodes:
            result.append(FlatNode(heading=str(node["heading"]).strip(), level=max(1, int(node["level"]))))
            children = node.get("children", [])
            if children:
                result.extend(self._flatten_nodes(children))
        return result

    def _dedupe_flat_nodes(self, nodes: list[FlatNode]) -> list[FlatNode]:
        result: list[FlatNode] = []
        seen: set[str] = set()
        for node in nodes:
            normalized = self._normalize_candidate(node.heading)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(node)
        return result

    def _build_tree(self, nodes: list[FlatNode]) -> list[OutlineNode]:
        roots: list[OutlineNode] = []
        stack: list[OutlineNode] = []

        for node in nodes:
            current = OutlineNode(heading=node.heading, level=max(1, node.level), children=[])
            while stack and stack[-1].level >= current.level:
                stack.pop()
            if stack:
                stack[-1].children.append(current)
            else:
                roots.append(current)
            stack.append(current)

        return roots

    def _node_to_dict(self, node: OutlineNode) -> dict:
        return {
            "heading": node.heading,
            "level": node.level,
            "children": [self._node_to_dict(child) for child in node.children],
        }

    def _nodes_to_markdown(self, nodes: list[OutlineNode]) -> str:
        lines: list[str] = []

        def walk(items: list[OutlineNode]) -> None:
            for item in items:
                indent = "  " * max(0, item.level - 1)
                lines.append(f"{indent}- {item.heading}")
                if item.children:
                    walk(item.children)

        walk(nodes)
        return "\n".join(lines)
