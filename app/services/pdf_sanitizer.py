from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass(slots=True)
class SanitizedPDFResult:
    sanitized_path: Path
    image_placeholders: int


class PDFSanitizer:
    def sanitize_images(self, source_path: Path, target_path: Path) -> SanitizedPDFResult:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        image_placeholders = 0

        try:
            with fitz.open(source_path) as document:
                if document.page_count == 0:
                    shutil.copy2(source_path, target_path)
                    return SanitizedPDFResult(sanitized_path=target_path, image_placeholders=0)

                for page in document:
                    seen_rects: set[tuple[float, float, float, float]] = set()
                    for image_info in page.get_images(full=True):
                        xref = int(image_info[0])
                        for rect in page.get_image_rects(xref):
                            key = tuple(round(value, 2) for value in (rect.x0, rect.y0, rect.x1, rect.y1))
                            if key in seen_rects:
                                continue
                            seen_rects.add(key)
                            page.add_redact_annot(
                                rect,
                                text=f"[Bild entfernt {image_placeholders + 1}]",
                                text_color=(0, 0, 0),
                                fill=(1, 1, 1),
                            )
                            image_placeholders += 1
                    if seen_rects:
                        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)

                    if page.rect.is_empty or page.rect.width <= 0 or page.rect.height <= 0:
                        raise ValueError("PDF enthält ungültige Seitengeometrie")

                if image_placeholders == 0:
                    shutil.copy2(source_path, target_path)
                    return SanitizedPDFResult(
                        sanitized_path=target_path,
                        image_placeholders=0,
                    )

                try:
                    document.save(target_path, garbage=4, deflate=True)
                except ValueError:
                    shutil.copy2(source_path, target_path)
                    return SanitizedPDFResult(
                        sanitized_path=target_path,
                        image_placeholders=0,
                    )

            return SanitizedPDFResult(sanitized_path=target_path, image_placeholders=image_placeholders)
        except Exception:
            if not target_path.exists():
                shutil.copy2(source_path, target_path)
            return SanitizedPDFResult(
                sanitized_path=target_path,
                image_placeholders=0,
            )
