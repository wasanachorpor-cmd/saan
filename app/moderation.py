"""Block newly introduced abuse before it can be read aloud."""

from __future__ import annotations

import re

from app.models import User, utcnow

# Whole-token slurs only. Short fragments are left out so a real Thai word is not caught.
_LATIN = (
    "fuck",
    "fucking",
    "motherfucker",
    "shit",
    "bullshit",
    "bitch",
    "asshole",
    "bastard",
    "cunt",
    "dick",
    "pussy",
    "nigger",
    "nigga",
    "faggot",
    "slut",
    "whore",
)
_THAI = ("ควย", "เหี้ย", "สัส", "เย็ด", "เชี่ย")
_INJECT = re.compile(r"<\s*/?\s*script\b|javascript\s*:|onerror\s*=|<\s*iframe\b", re.I)


def terms_in(text: str) -> set[str]:
    """Return abuse tokens present in text. Matching ignores dots and spaces inside a Latin word."""
    sample = text or ""
    folded = sample.casefold()
    compact = re.sub(r"(?<=[a-z])[^a-z]+(?=[a-z])", "", folded)
    found: set[str] = set()
    for word in _LATIN:
        if word in compact:
            found.add(word)
    for word in _THAI:
        if re.search(rf"(?<![\u0E00-\u0E7F]){re.escape(word)}(?![\u0E00-\u0E7F])", sample):
            found.add(word)
    return found


def is_blocked(text: str) -> bool:
    return bool(terms_in(text)) or bool(_INJECT.search(text or ""))


def abuse_introduced(original: str, edited: str) -> bool:
    """True when the edit adds a slur or a script that the page text did not already contain."""
    if terms_in(edited) - terms_in(original):
        return True
    return bool(_INJECT.search(edited or "")) and not _INJECT.search(original or "")


def suspend(user: User) -> None:
    if user.suspended_at is None:
        user.suspended_at = utcnow()
    user.trust = 0
