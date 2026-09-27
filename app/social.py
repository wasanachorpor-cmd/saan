"""LINE and Facebook sign-in. Email login stays available when these are not configured."""

from __future__ import annotations

import re
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.errors import AppError
from app.i18n import STRINGS
from app.moderation import is_blocked
from app.models import User
from app.security import hash_password
from app.web import language_of, render

router = APIRouter()


def _configured(provider: str) -> bool:
    settings = get_settings()
    if provider == "line":
        return bool(settings.line_channel_id.strip() and settings.line_channel_secret.strip())
    if provider == "facebook":
        return bool(settings.facebook_app_id.strip() and settings.facebook_app_secret.strip())
    return False


def _callback(provider: str) -> str:
    return get_settings().public_base_url.rstrip("/") + f"/auth/{provider}/callback"


def _login_page(request: Request, error: str, status: int = 400):
    t = STRINGS[language_of(request)]
    return render(request, "login.html", status=status, title=t["login_title"], error=error, next="")


def _clean_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", name or "").strip()
    if len(cleaned) < 2 or is_blocked(cleaned):
        return "S.A.A.N."
    return cleaned[:80]


def _account(db: Session, provider: str, subject: str, email: str | None, name: str, role: str) -> User:
    found = (
        db.query(User)
        .filter(User.auth_provider == provider, User.provider_subject == subject)
        .one_or_none()
    )
    if found:
        return found
    if email:
        by_email = db.query(User).filter(User.email == email).one_or_none()
        if by_email is not None:
            if by_email.provider_subject and by_email.provider_subject != subject:
                raise AppError("social_conflict", 409)
            by_email.auth_provider = provider
            by_email.provider_subject = subject
            db.commit()
            return by_email
    else:
        email = f"{provider}.{subject}@users.saan.local"
    user = User(
        email=email,
        display_name=_clean_name(name),
        password_hash=hash_password(secrets.token_urlsafe(32)),
        role=role,
        points=0,
        trust=50,
        auth_provider=provider,
        provider_subject=subject,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _open_session(request: Request, user: User) -> RedirectResponse:
    request.session.clear()
    request.session["uid"] = user.id
    request.session["role"] = user.role
    request.session["csrf"] = secrets.token_urlsafe(32)
    dest = "/mission" if user.role == "volunteer" else "/read"
    return RedirectResponse(dest, status_code=303)


@router.get("/auth/{provider}")
def start(provider: str, request: Request):
    if provider not in {"line", "facebook"}:
        raise AppError("not_found", 404)
    role = request.query_params.get("role")
    if role not in {"reader", "volunteer"}:
        role = "reader"
    if not _configured(provider):
        return _login_page(request, "social_unconfigured", 503)
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    request.session["oauth_role"] = role
    settings = get_settings()
    if provider == "line":
        query = urlencode(
            {
                "response_type": "code",
                "client_id": settings.line_channel_id.strip(),
                "redirect_uri": _callback("line"),
                "state": state,
                "scope": "profile openid",
            }
        )
        return RedirectResponse(f"https://access.line.me/oauth2/v2.1/authorize?{query}", status_code=303)
    query = urlencode(
        {
            "client_id": settings.facebook_app_id.strip(),
            "redirect_uri": _callback("facebook"),
            "state": state,
            "scope": "email,public_profile",
            "response_type": "code",
        }
    )
    return RedirectResponse(f"https://www.facebook.com/v19.0/dialog/oauth?{query}", status_code=303)


@router.get("/auth/{provider}/callback")
def callback(provider: str, request: Request, db: Session = Depends(get_db)):
    if provider not in {"line", "facebook"}:
        raise AppError("not_found", 404)
    if request.query_params.get("error"):
        return _login_page(request, "social_failed")
    state = request.query_params.get("state") or ""
    code = request.query_params.get("code") or ""
    if not code or state != request.session.get("oauth_state"):
        return _login_page(request, "social_failed")
    role = request.session.get("oauth_role")
    if role not in {"reader", "volunteer"}:
        role = "reader"
    try:
        subject, email, name = _profile(provider, code)
        user = _account(db, provider, subject, email, name, role)
    except AppError as exc:
        return _login_page(request, exc.code, exc.status)
    except Exception:
        return _login_page(request, "social_failed")
    if user.suspended_at is not None:
        return _login_page(request, "account_suspended", 403)
    return _open_session(request, user)


def _profile(provider: str, code: str) -> tuple[str, str | None, str]:
    settings = get_settings()
    with httpx.Client(timeout=15) as client:
        if provider == "line":
            token = client.post(
                "https://api.line.me/oauth2/v2.1/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": _callback("line"),
                    "client_id": settings.line_channel_id.strip(),
                    "client_secret": settings.line_channel_secret.strip(),
                },
            )
            token.raise_for_status()
            access = token.json().get("access_token")
            if not access:
                raise RuntimeError("line token")
            profile = client.get(
                "https://api.line.me/v2/profile",
                headers={"Authorization": f"Bearer {access}"},
            )
            profile.raise_for_status()
            body = profile.json()
            return str(body["userId"]), None, str(body.get("displayName") or "")
        token = client.get(
            "https://graph.facebook.com/v19.0/oauth/access_token",
            params={
                "client_id": settings.facebook_app_id.strip(),
                "client_secret": settings.facebook_app_secret.strip(),
                "redirect_uri": _callback("facebook"),
                "code": code,
            },
        )
        token.raise_for_status()
        access = token.json().get("access_token")
        if not access:
            raise RuntimeError("facebook token")
        profile = client.get(
            "https://graph.facebook.com/me",
            params={"fields": "id,name,email", "access_token": access},
        )
        profile.raise_for_status()
        body = profile.json()
        email = str(body.get("email") or "").strip().lower() or None
        return str(body["id"]), email, str(body.get("name") or "")
