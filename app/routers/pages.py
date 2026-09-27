"""HTML pages for the reader desk and volunteer mission control."""

from __future__ import annotations

import re
import secrets
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AppError
from app.i18n import STRINGS
from app.limits import allow
from app.moderation import is_blocked
from app.models import Document, User
from app.security import csrf_ok, hash_password, safe_next, verify_password
from app.services import documents as docs
from app.services import volunteers
from app.web import current_user, language_of, render

router = APIRouter()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _home(user: User) -> str:
    return "/mission" if user.role == "volunteer" else "/read"


def _redirect_login(request: Request) -> RedirectResponse:
    return RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)


async def _form(request: Request):
    form = await request.form()
    if not csrf_ok(request, str(form.get("csrf") or "")):
        raise AppError("csrf", 403)
    return form


def _db_user(request: Request, db: Session) -> User | None:
    uid = request.session.get("uid")
    if not uid:
        return None
    user = db.get(User, int(uid))
    if user is not None and user.suspended_at is not None:
        request.session.clear()
        raise AppError("account_suspended", 403)
    return user


def _login_session(request: Request, user: User) -> None:
    request.session.clear()
    request.session["uid"] = user.id
    request.session["role"] = user.role
    request.session["csrf"] = secrets.token_urlsafe(32)


@router.get("/")
def home(request: Request):
    return render(request, "index.html", title=STRINGS[language_of(request)]["hero_title"])


@router.get("/about")
def about(request: Request):
    t = STRINGS[language_of(request)]
    return render(request, "about.html", title=t["about_title"])


@router.get("/accessibility")
def accessibility(request: Request):
    t = STRINGS[language_of(request)]
    return render(request, "accessibility.html", title=t["a11y_title"])


@router.get("/login")
def login_form(request: Request):
    user = current_user(request)
    if user:
        return RedirectResponse(_home(user), status_code=303)
    t = STRINGS[language_of(request)]
    return render(request, "login.html", title=t["login_title"], next=safe_next(request.query_params.get("next"), ""))


@router.post("/login")
async def login_submit(request: Request, db: Session = Depends(get_db)):
    form = await _form(request)
    t = STRINGS[language_of(request)]
    email = str(form.get("email") or "").strip().lower()
    password = str(form.get("password") or "")
    user = db.query(User).filter(User.email == email).one_or_none()
    nxt = safe_next(str(form.get("next") or ""), "")
    if user is None or not verify_password(password, user.password_hash):
        return render(
            request,
            "login.html",
            status=400,
            title=t["login_title"],
            error="err_credentials",
            next=nxt,
            email=email,
        )
    if user.suspended_at is not None:
        return render(
            request,
            "login.html",
            status=403,
            title=t["login_title"],
            error="account_suspended",
            next=nxt,
            email=email,
        )
    _login_session(request, user)
    if user.role == "reader" and nxt.startswith(("/read", "/library")):
        dest = nxt
    elif user.role == "volunteer" and nxt.startswith("/mission"):
        dest = nxt
    else:
        dest = _home(user)
    return RedirectResponse(dest, status_code=303)


@router.get("/register")
def register_form(request: Request):
    user = current_user(request)
    if user:
        return RedirectResponse(_home(user), status_code=303)
    t = STRINGS[language_of(request)]
    return render(request, "register.html", title=t["register_title"])


@router.post("/register")
async def register_submit(request: Request, db: Session = Depends(get_db)):
    form = await _form(request)
    t = STRINGS[language_of(request)]
    email = str(form.get("email") or "").strip().lower()
    name = re.sub(r"\s+", " ", str(form.get("display_name") or "")).strip()
    password = str(form.get("password") or "")
    role = str(form.get("role") or "")
    error = None
    if not EMAIL_RE.match(email):
        error = "err_email"
    elif len(name) < 2 or len(name) > 80:
        error = "err_name"
    elif len(password) < 8:
        error = "err_password_short"
    elif role not in {"reader", "volunteer"}:
        error = "err_role"
    elif is_blocked(name):
        error = "err_name_blocked"
    elif db.query(User).filter(User.email == email).one_or_none():
        error = "err_email_taken"
    if error:
        return render(
            request,
            "register.html",
            status=400,
            title=t["register_title"],
            error=error,
            email=email,
            display_name=name,
            role=role,
        )
    user = User(email=email, display_name=name, password_hash=hash_password(password), role=role, points=0)
    db.add(user)
    db.commit()
    db.refresh(user)
    _login_session(request, user)
    return RedirectResponse(_home(user), status_code=303)


@router.post("/logout")
async def logout(request: Request):
    await _form(request)
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@router.post("/prefs/{key}")
async def prefs(key: str, request: Request):
    form = await _form(request)
    nxt = safe_next(str(form.get("next") or "/"), "/")
    fetch = request.headers.get("x-saan-fetch") == "1"
    response: Response
    if fetch:
        response = Response(status_code=204)
    else:
        response = RedirectResponse(nxt, status_code=303)

    if key == "contrast":
        current = request.cookies.get("saan_contrast", "night")
        value = "high" if current != "high" else "night"
        response.set_cookie("saan_contrast", value, max_age=60 * 60 * 24 * 365, samesite="lax", path="/")
    elif key == "lang":
        value = str(form.get("value") or "")
        if value in {"en", "th"}:
            response.set_cookie("saan_lang", value, max_age=60 * 60 * 24 * 365, samesite="lax", path="/")
    elif key == "font":
        value = str(form.get("value") or "")
        if value in {"sm", "md", "lg", "xl"}:
            response.set_cookie("saan_font", value, max_age=60 * 60 * 24 * 365, samesite="lax", path="/")
    else:
        raise AppError("not_found", 404)
    return response


@router.get("/read")
def read_desk(request: Request):
    user = current_user(request)
    if user is None:
        return _redirect_login(request)
    if user.role != "reader":
        raise AppError("forbidden_volunteer", 403)
    t = STRINGS[language_of(request)]
    return render(request, "read.html", title=t["desk_title"])


@router.get("/read/{document_id}")
def read_document(document_id: int, request: Request, db: Session = Depends(get_db)):
    user = _db_user(request, db)
    if user is None:
        return _redirect_login(request)
    if user.role != "reader":
        raise AppError("forbidden_volunteer", 403)
    document = docs.owned_document(db, user, document_id)
    return render(request, "read.html", title=document.original_filename, document=document)


@router.get("/library")
def library(request: Request, db: Session = Depends(get_db)):
    user = _db_user(request, db)
    if user is None:
        return _redirect_login(request)
    if user.role != "reader":
        raise AppError("forbidden_volunteer", 403)
    t = STRINGS[language_of(request)]
    return render(
        request,
        "library.html",
        title=t["library_title"],
        documents=docs.list_documents(db, user),
    )


@router.post("/documents")
async def upload(request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    user = _db_user(request, db)
    if user is None:
        raise AppError("login_required", 401)
    if not allow(f"user:{user.id}", 8, 600) or not allow(f"ip:{request.client.host if request.client else 'local'}", 30, 600):
        raise AppError("upload_rate", 429)
    form = await _form(request)
    upload_file = form.get("image")
    if upload_file is None or not getattr(upload_file, "filename", ""):
        raise AppError("upload_need_file", 400)
    data = await upload_file.read()
    document = docs.create_upload(db, user, upload_file.filename, data)
    background.add_task(docs.process_document, document.id)
    if request.headers.get("x-saan-fetch") == "1":
        from fastapi.responses import JSONResponse

        return JSONResponse({"id": document.id, "location": f"/read/{document.id}"})
    return RedirectResponse(f"/read/{document.id}", status_code=303)


@router.post("/documents/{document_id}/snippets/{snippet_id}/flag")
async def flag(document_id: int, snippet_id: int, request: Request, db: Session = Depends(get_db)):
    user = _db_user(request, db)
    if user is None:
        raise AppError("login_required", 401)
    form = await _form(request)
    docs.flag_snippet(db, user, document_id, snippet_id, str(form.get("note") or ""))
    request.session["flash"] = "report_sent"
    return RedirectResponse(f"/read/{document_id}", status_code=303)


@router.post("/documents/{document_id}/delete")
async def remove(document_id: int, request: Request, db: Session = Depends(get_db)):
    user = _db_user(request, db)
    if user is None:
        raise AppError("login_required", 401)
    await _form(request)
    docs.delete_document(db, user, document_id)
    request.session["flash"] = "deleted"
    return RedirectResponse("/library", status_code=303)


@router.get("/documents/{document_id}/image")
def document_image(document_id: int, request: Request, db: Session = Depends(get_db)):
    user = _db_user(request, db)
    if user is None:
        raise AppError("login_required", 401)
    document = db.get(Document, document_id)
    if document is None:
        raise AppError("not_found", 404)
    if user.role == "reader" and document.owner_id != user.id:
        raise AppError("not_found", 404)
    if user.role == "volunteer" and not docs.volunteer_can_view(document):
        raise AppError("forbidden", 403)
    path = docs.upload_path(document.stored_name)
    if not path.exists():
        raise AppError("not_found", 404)
    media = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media, content_disposition_type="inline")


@router.get("/documents/{document_id}/text")
def document_text(document_id: int, request: Request, db: Session = Depends(get_db)):
    user = _db_user(request, db)
    if user is None:
        raise AppError("login_required", 401)
    if user.role != "reader":
        raise AppError("forbidden", 403)
    document = docs.owned_document(db, user, document_id)
    body = docs.transcript(document)
    filename = docs.safe_filename(document.original_filename)
    if not filename.lower().endswith(".txt"):
        filename = f"{filename}.txt"
    return Response(
        content=body,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"page.txt\"; filename*=UTF-8''{quote(filename)}"
        },
    )


@router.get("/mission")
def mission(request: Request, db: Session = Depends(get_db)):
    user = _db_user(request, db)
    if user is None:
        return _redirect_login(request)
    if user.role != "volunteer":
        raise AppError("forbidden_reader", 403)
    t = STRINGS[language_of(request)]
    period = request.query_params.get("board") or "month"
    if period not in {"day", "month", "year"}:
        period = "month"
    return render(
        request,
        "mission.html",
        title=t["mission_title"],
        queue=volunteers.queue(db),
        pending=volunteers.pending_edits(db),
        stats=volunteers.stats_for(db, user),
        leaders=volunteers.leaderboard(db, user, period),
        board=period,
    )


@router.get("/mission/{snippet_id}")
def review(snippet_id: int, request: Request, db: Session = Depends(get_db)):
    user = _db_user(request, db)
    if user is None:
        return _redirect_login(request)
    if user.role != "volunteer":
        raise AppError("forbidden_reader", 403)
    snippet = volunteers.get_snippet(db, snippet_id)
    if snippet.status == "extracted":
        raise AppError("unflagged_block", 404)
    t = STRINGS[language_of(request)]
    return render(
        request,
        "review.html",
        title=t["review_title"],
        snippet=snippet,
        state=volunteers.claim_state(snippet, user),
    )


@router.post("/mission/{snippet_id}/claim")
async def claim(snippet_id: int, request: Request, db: Session = Depends(get_db)):
    user = _db_user(request, db)
    if user is None:
        raise AppError("login_required", 401)
    await _form(request)
    volunteers.claim(db, user, snippet_id)
    return RedirectResponse(f"/mission/{snippet_id}", status_code=303)


@router.post("/mission/{snippet_id}/correct")
async def save_correction(snippet_id: int, request: Request, db: Session = Depends(get_db)):
    user = _db_user(request, db)
    if user is None:
        raise AppError("login_required", 401)
    form = await _form(request)
    try:
        points, badges = volunteers.correct(db, user, snippet_id, str(form.get("text") or ""))
    except AppError as exc:
        if exc.code == "account_suspended":
            request.session.clear()
            raise
        snippet = volunteers.get_snippet(db, snippet_id)
        t = STRINGS[language_of(request)]
        return render(
            request,
            "review.html",
            status=exc.status,
            title=t["review_title"],
            snippet=snippet,
            state=volunteers.claim_state(snippet, user),
            error=exc.code,
            draft=str(form.get("text") or ""),
        )
    if points == 0:
        request.session["flash"] = "held_for_review"
    else:
        request.session["flash"] = "saved"
        request.session["earned"] = points
        request.session["new_badges"] = badges
    return RedirectResponse("/mission", status_code=303)


@router.post("/mission/edits/{edit_id}/moderate")
async def moderate(edit_id: int, request: Request, db: Session = Depends(get_db)):
    user = _db_user(request, db)
    if user is None:
        raise AppError("login_required", 401)
    form = await _form(request)
    volunteers.moderate(db, user, edit_id, str(form.get("decision") or ""))
    request.session["flash"] = "moderated"
    return RedirectResponse("/mission", status_code=303)
