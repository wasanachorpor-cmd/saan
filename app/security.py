"""Password hashing, CSRF checks, and local redirect guards."""

import base64
import hashlib
import hmac
import secrets

from starlette.requests import Request

PBKDF2_ROUNDS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds_s, salt_b64, digest_b64 = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rounds_s))
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def ensure_csrf(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


def csrf_ok(request: Request, token: str | None) -> bool:
    expected = request.session.get("csrf") or ""
    given = token or ""
    if not expected or not given:
        return False
    try:
        return hmac.compare_digest(given, expected)
    except (TypeError, ValueError):
        return False


def safe_next(value: str | None, default: str = "/") -> str:
    """Allow only same-site relative paths."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return default
    return value
