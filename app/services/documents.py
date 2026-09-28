"""Page uploads, OCR jobs, and reader flags."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import timedelta
from io import BytesIO
from pathlib import Path

from PIL import Image
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import AppError
from app.moderation import is_blocked, suspend
from app.models import Document, Snippet, User, utcnow
from app.ocr import looks_complex, run_ocr, split_text, text_language

log = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = 24_000_000
IMAGE_KEEP = timedelta(hours=24)


def sniff_image(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if len(data) > 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    return None


def _clean_image(data: bytes, ext: str) -> bytes:
    """Re-save a real photo so extra chunks and embedded files are dropped."""
    try:
        with Image.open(BytesIO(data)) as checked:
            checked.verify()
        with Image.open(BytesIO(data)) as image:
            image.load()
            if image.width < 1 or image.height < 1 or image.width > 8000 or image.height > 8000:
                raise AppError("upload_too_big", 400)
            frame = image
            if ext == ".jpg" or frame.mode not in {"RGB", "RGBA", "L"}:
                frame = frame.convert("RGB")
            out = BytesIO()
            if ext == ".jpg":
                frame.save(out, format="JPEG", quality=90)
            elif ext == ".webp":
                frame.save(out, format="WEBP", quality=85)
            else:
                frame.save(out, format="PNG")
            cleaned = out.getvalue()
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AppError("upload_not_image", 400) from exc
    if sniff_image(cleaned) is None:
        raise AppError("upload_not_image", 400)
    return cleaned


def safe_filename(name: str | None) -> str:
    raw = (name or "page").strip().replace("\\", "/").split("/")[-1]
    raw = re.sub(r"[^\w.\- ]+", "", raw, flags=re.UNICODE).strip()
    return (raw or "page")[:180]


def upload_path(stored_name: str) -> Path:
    root = get_settings().resolved_upload_dir().resolve()
    path = (root / stored_name).resolve()
    if path.parent != root:
        raise AppError("not_found", 404)
    return path


def owned_document(db: Session, user: User, document_id: int) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.owner_id != user.id:
        raise AppError("not_found", 404)
    return document


def create_upload(db: Session, user: User, filename: str | None, data: bytes) -> Document:
    if user.role != "reader":
        raise AppError("forbidden_volunteer", 403)
    settings = get_settings()
    if not data:
        raise AppError("upload_empty", 400)
    if len(data) > settings.max_upload_bytes:
        raise AppError("upload_too_big", 400)
    ext = sniff_image(data)
    if ext is None:
        raise AppError("upload_bad_type", 400)
    data = _clean_image(data, ext)
    stored = f"{uuid.uuid4().hex}{ext}"
    upload_path(stored).write_bytes(data)
    document = Document(
        owner_id=user.id,
        original_filename=safe_filename(filename),
        stored_name=stored,
        status="processing",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def process_document(document_id: int) -> None:
    """Run OCR on a background thread. Uses its own database session."""
    from app.database import SessionLocal

    if SessionLocal is None:
        return
    db = SessionLocal()
    try:
        document = db.get(Document, document_id)
        if document is None:
            return
        path = upload_path(document.stored_name)
        try:
            result = run_ocr(path)
            parts = split_text(result.text)
            if not parts:
                document.status = "failed"
                document.error_message = "ocr_empty"
                schedule_image_purge(document)
            else:
                kind = looks_complex(result.text, result.confidence)
                document.layout_kind = kind
                for index, part in enumerate(parts):
                    db.add(
                        Snippet(
                            document_id=document.id,
                            sequence=index,
                            original_text=part,
                            current_text=part,
                            confidence=result.confidence,
                            language=text_language(part),
                            status="flagged" if kind else "extracted",
                            flag_note="complex_layout" if kind else None,
                            flagged_at=utcnow() if kind else None,
                        )
                    )
                document.status = "flagged" if kind else "ready"
                document.engine = result.engine
                document.confidence = result.confidence
                document.error_message = None
                schedule_image_purge(document)
                log.info(
                    "OCR ready document=%s engine=%s confidence=%s chars=%s",
                    document.id,
                    result.engine,
                    result.confidence,
                    sum(len(part) for part in parts),
                )
        except Exception as exc:  # noqa: BLE001
            document.status = "failed"
            message = str(exc) or "ocr_failed"
            document.error_message = "ocr_empty" if message == "ocr_empty" else message[:400]
            schedule_image_purge(document)
            log.warning("OCR failed document=%s", document.id)
        document.updated_at = utcnow()
        db.commit()
    finally:
        db.close()


def list_documents(db: Session, user: User) -> list[Document]:
    return (
        db.query(Document)
        .filter(Document.owner_id == user.id)
        .order_by(Document.created_at.desc())
        .all()
    )


def flag_snippet(db: Session, user: User, document_id: int, snippet_id: int, note: str) -> None:
    document = owned_document(db, user, document_id)
    snippet = db.get(Snippet, snippet_id)
    if snippet is None or snippet.document_id != document.id:
        raise AppError("not_found", 404)
    if document.status in {"processing", "failed"} or not snippet.current_text:
        raise AppError("unflagged_block", 400)
    cleaned_note = (note or "").strip()[:500]
    if cleaned_note and is_blocked(cleaned_note):
        suspend(user)
        db.commit()
        raise AppError("account_suspended", 403)
    snippet.status = "flagged"
    snippet.flag_note = cleaned_note or None
    snippet.flagged_at = utcnow()
    snippet.claimed_by_id = None
    snippet.claimed_at = None
    snippet.verified_at = None
    document.status = "flagged"
    document.updated_at = utcnow()
    schedule_image_purge(document)
    db.commit()


def recompute_document(document: Document) -> None:
    statuses = [snippet.status for snippet in document.snippets]
    if any(status in {"flagged", "in_review"} for status in statuses):
        document.status = "flagged"
    elif statuses and all(status == "verified" for status in statuses):
        document.status = "verified"
    elif document.status != "failed":
        document.status = "ready"
    document.updated_at = utcnow()
    schedule_image_purge(document)


def schedule_image_purge(document: Document) -> None:
    """Keep the photo while a volunteer still needs it, then delete it after 24 hours."""
    if document.image_purged_at is not None:
        return
    busy = any(snippet.status in {"flagged", "in_review"} for snippet in document.snippets)
    if document.status == "processing" or busy:
        document.image_purge_at = None
        return
    if document.status in {"ready", "verified", "failed"} and document.image_purge_at is None:
        document.image_purge_at = utcnow() + IMAGE_KEEP


def purge_expired_images(db: Session) -> int:
    now = utcnow()
    rows = (
        db.query(Document)
        .filter(
            Document.image_purge_at.is_not(None),
            Document.image_purge_at <= now,
            Document.image_purged_at.is_(None),
        )
        .all()
    )
    removed = 0
    for document in rows:
        busy = any(snippet.status in {"flagged", "in_review"} for snippet in document.snippets)
        if busy:
            document.image_purge_at = None
            continue
        path = upload_path(document.stored_name)
        if path.exists():
            path.unlink()
            removed += 1
        document.image_purged_at = now
        document.image_purge_at = None
    if rows:
        db.commit()
    return removed


def delete_document(db: Session, user: User, document_id: int) -> None:
    document = owned_document(db, user, document_id)
    path = upload_path(document.stored_name)
    db.delete(document)
    db.commit()
    if path.exists():
        path.unlink()


def transcript(document: Document) -> str:
    return "\n\n".join(snippet.current_text for snippet in document.snippets if snippet.current_text)


def volunteer_can_view(document: Document) -> bool:
    return any(snippet.status in {"flagged", "in_review", "verified"} for snippet in document.snippets)
