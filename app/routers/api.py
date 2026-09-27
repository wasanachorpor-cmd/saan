"""JSON and event-stream endpoints used by the reading desk and the queue."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from app import database
from app.database import get_db
from app.errors import AppError
from app.models import Document
from app.limits import allow
from app.security import csrf_ok
from app.services import documents as docs
from app.services import volunteers
from app.speech import synthesize
from app.web import current_user

_WELCOME = {
    # The on-screen line keeps the official wording. This spoken line is the same greeting
    # in a form the Thai voice can actually pronounce.
    "th": "ยินดีต้อนรับสู่เอสเอเอ็น แพลตฟอร์มเทคโนโลยี เพื่อให้ทุกคนเรียนได้อย่างเท่าเทียม",
    "en": "Welcome to S.A.A.N., a platform for equal access to learning.",
}
_welcome_audio: dict[str, bytes] = {}

router = APIRouter(prefix="/api")


def _require(request: Request):
    user = current_user(request)
    if user is None:
        raise AppError("login_required", 401)
    return user


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    lang: str = "th-TH"
    rate: float = 1.0


@router.get("/health")
def health():
    return {"ok": True, "name": "S.A.A.N."}


@router.get("/welcome")
async def welcome(request: Request, lang: str = "th"):
    """Speak only the fixed greeting, so this cannot be used as an open voice service."""
    choice = lang if lang in _WELCOME else "th"
    host = request.client.host if request.client else "local"
    if not allow(f"welcome:{host}", 20, 600):
        raise AppError("welcome_busy", 429)
    if choice not in _welcome_audio:
        voice = "th-TH" if choice == "th" else "en-US"
        audio = b""
        error: Exception | None = None
        for _ in range(2):
            try:
                audio = await synthesize(_WELCOME[choice], voice, 1.0)
                error = None
                break
            except Exception as exc:  # noqa: BLE001
                error = exc
        if error is not None or not audio:
            raise AppError("welcome_busy", 503) from error
        _welcome_audio[choice] = audio
    return Response(content=_welcome_audio[choice], media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=86400"})


@router.post("/speak")
async def speak(body: SpeakRequest, request: Request):
    user = _require(request)
    if user.role != "reader":
        raise AppError("forbidden", 403)
    token = request.headers.get("x-csrf")
    if not csrf_ok(request, token):
        raise AppError("csrf", 403)
    audio = await synthesize(body.text.strip(), body.lang, body.rate)
    return Response(content=audio, media_type="audio/mpeg")


@router.get("/documents/{document_id}")
def document_status(document_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require(request)
    if user.role != "reader":
        raise AppError("forbidden", 403)
    document = docs.owned_document(db, user, document_id)
    return {
        "id": document.id,
        "status": document.status,
        "engine": document.engine,
        "error": document.error_message,
    }


@router.get("/documents/{document_id}/events")
async def document_events(document_id: int, request: Request):
    user = _require(request)
    if user.role != "reader":
        raise AppError("forbidden", 403)

    async def stream():
        while True:
            if await request.is_disconnected():
                break
            payload = await asyncio.to_thread(_snapshot, document_id, user.id)
            if payload is None:
                yield 'data: {"status": "missing"}\n\n'
                break
            yield f"data: {json.dumps(payload)}\n\n"
            if payload["status"] != "processing":
                break
            await asyncio.sleep(0.8)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _snapshot(document_id: int, owner_id: int) -> dict | None:
    if database.SessionLocal is None:
        return None
    db = database.SessionLocal()
    try:
        document = db.get(Document, document_id)
        if document is None or document.owner_id != owner_id:
            return None
        return {"id": document.id, "status": document.status, "error": document.error_message}
    finally:
        db.close()


@router.get("/queue")
def queue(request: Request, db: Session = Depends(get_db)):
    user = _require(request)
    if user.role != "volunteer":
        raise AppError("forbidden", 403)
    items = volunteers.queue(db)
    return JSONResponse(
        {
            "count": len(items),
            "items": [
                {
                    "id": item.id,
                    "status": item.status,
                    "excerpt": item.current_text[:180],
                    "language": item.language,
                }
                for item in items
            ],
        }
    )
