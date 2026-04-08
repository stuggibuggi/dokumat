from __future__ import annotations

from datetime import datetime
import shutil
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile

from app.config import Settings


class StorageService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def ensure_directories(self) -> None:
        self.settings.originals_dir.mkdir(parents=True, exist_ok=True)
        self.settings.images_dir.mkdir(parents=True, exist_ok=True)
        self.settings.sanitized_dir.mkdir(parents=True, exist_ok=True)
        self.settings.outline_results_dir.mkdir(parents=True, exist_ok=True)
        self.settings.templates_dir.mkdir(parents=True, exist_ok=True)
        self.settings.template_check_results_dir.mkdir(parents=True, exist_ok=True)

    def _safe_filename(self, filename: str) -> str:
        safe = Path(filename).name.strip() or "document.pdf"
        return safe.replace(" ", "_")

    def _document_pdf_dir(self, document_id: UUID) -> Path:
        path = self.settings.originals_dir / str(document_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def document_image_dir(self, document_id: UUID) -> Path:
        path = self.settings.images_dir / str(document_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def reset_document_image_dir(self, document_id: UUID) -> Path:
        path = self.settings.images_dir / str(document_id)
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_upload(self, document_id: UUID, upload: UploadFile) -> Path:
        target = self._document_pdf_dir(document_id) / self._safe_filename(upload.filename or "upload.pdf")
        with target.open("wb") as output:
            shutil.copyfileobj(upload.file, output)
        return target

    def copy_example_pdf(self, document_id: UUID, source_path: Path) -> Path:
        target = self._document_pdf_dir(document_id) / self._safe_filename(source_path.name)
        shutil.copy2(source_path, target)
        return target

    def create_sanitized_pdf_target(self, original_filename: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_name = self._safe_filename(Path(original_filename).stem)
        target = self.settings.sanitized_dir / f"{timestamp}-{safe_name}-sanitized.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def create_outline_json_target(self, original_filename: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_name = self._safe_filename(Path(original_filename).stem)
        target = self.settings.outline_results_dir / f"{timestamp}-{safe_name}-outline.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def save_template_upload(self, template_id: UUID, upload: UploadFile) -> Path:
        path = self.settings.templates_dir / str(template_id)
        path.mkdir(parents=True, exist_ok=True)
        target = path / self._safe_filename(upload.filename or "template.pdf")
        with target.open("wb") as output:
            shutil.copyfileobj(upload.file, output)
        return target

    def create_template_check_json_target(self, template_name: str, document_name: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        template_part = self._safe_filename(Path(template_name).stem)
        document_part = self._safe_filename(Path(document_name).stem)
        target = self.settings.template_check_results_dir / f"{timestamp}-{template_part}-{document_part}-check.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def to_relative(self, path: Path) -> str:
        return path.relative_to(self.settings.base_dir).as_posix()

    def to_absolute(self, relative_path: str) -> Path:
        return self.settings.base_dir / relative_path
