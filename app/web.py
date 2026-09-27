"""Shared template rendering and the signed-in user."""

from __future__ import annotations

from datetime import timedelta, timezone
from pathlib import Path

from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from starlette.requests import Request
from starlette.responses import Response

from app.config import ROOT, get_settings
from app import database
from app.i18n import LANGS, STRINGS
from app.ocr import repair_thai
from app.models import User
from app.security import ensure_csrf

templates = Jinja2Templates(directory=str(ROOT / "templates"))


_BANGKOK = timezone(timedelta(hours=7))
_THAI_MONTHS = (
    "ม.ค.",
    "ก.พ.",
    "มี.ค.",
    "เม.ย.",
    "พ.ค.",
    "มิ.ย.",
    "ก.ค.",
    "ส.ค.",
    "ก.ย.",
    "ต.ค.",
    "พ.ย.",
    "ธ.ค.",
)


def format_local(value, lang: str = "en") -> str:
    """Show a stored UTC clock in Thailand, without a daylight-saving shift."""
    if not value:
        return ""
    moment = value
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local = moment.astimezone(_BANGKOK)
    if lang == "th":
        month = _THAI_MONTHS[local.month - 1]
        return f"{local.day} {month} {local.year} เวลา {local:%H:%M} น."
    return local.strftime("%d %b %Y, %H:%M")


@pass_context
def format_when(context, value) -> str:
    lang = "en"
    if context is not None:
        lang = context.get("lang", "en")
    return format_local(value, lang)


templates.env.filters["when"] = format_when
templates.env.filters["thai"] = lambda value: repair_thai(value) if isinstance(value, str) else value


def current_user(request: Request) -> User | None:
    uid = request.session.get("uid")
    if not uid or database.SessionLocal is None:
        return None
    db = database.SessionLocal()
    try:
        user = db.get(User, uid)
        if user is None or user.suspended_at is not None:
            return None
        db.expunge(user)
        return user
    finally:
        db.close()


def language_of(request: Request) -> str:
    lang = request.cookies.get("saan_lang", "en")
    return lang if lang in LANGS else "en"


def render(request: Request, name: str, status: int = 200, **context) -> Response:
    lang = language_of(request)
    contrast = request.cookies.get("saan_contrast", "night")
    if contrast not in {"night", "high"}:
        contrast = "night"
    font = request.cookies.get("saan_font", "md")
    if font not in {"sm", "md", "lg", "xl"}:
        font = "md"
    strings = STRINGS[lang]
    flash = request.session.pop("flash", None)
    if flash not in strings:
        flash = None
    earned = request.session.pop("earned", None)
    new_badges = request.session.pop("new_badges", None) or []
    payload = {
        "request": request,
        "t": strings,
        "lang": lang,
        "user": current_user(request),
        "csrf": ensure_csrf(request),
        "contrast": contrast,
        "font": font,
        "flash": flash,
        "earned": earned,
        "new_badges": new_badges,
        "gemini_on": bool(get_settings().gemini_api_key.strip()),
        "title": context.pop("title", strings["app_name"]),
    }
    payload.update(context)
    response = templates.TemplateResponse(request, name, payload, status_code=status)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "script-src 'self'; "
        "connect-src 'self'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "object-src 'none'"
    )
    return response


def static_dir() -> Path:
    return ROOT / "static"
