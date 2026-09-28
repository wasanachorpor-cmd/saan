"""Spoken audio for languages the browser cannot pronounce."""

from __future__ import annotations

import asyncio
import re

_SOFT = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u200b-\u200f\ufeff]")
_KEEP = re.compile(r"[^\u0E00-\u0E7FA-Za-z0-9\s.,;:'\"!?()%\-+/…“”‘’]")
_VOICE = asyncio.Lock()

_VOICES = {
    "th": "th-TH-PremwadeeNeural",
    "en": "en-US-JennyNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "ar": "ar-SA-ZariyahNeural",
    "hi": "hi-IN-SwaraNeural",
    "he": "he-IL-HilaNeural",
}


def voice_for(lang: str) -> str:
    prefix = (lang or "en").lower().replace("_", "-")[:2]
    return _VOICES.get(prefix, _VOICES["en"])


def _rate(rate: float) -> str:
    bounded = min(2.0, max(0.5, rate))
    percent = int(round((bounded - 1.0) * 100))
    return f"{percent:+d}%"


def _clean(text: str) -> str:
    text = _KEEP.sub(" ", _SOFT.sub("", text))
    return re.sub(r"[ \t]+", " ", text).strip()


_ACRONYM = re.compile(r"S\s*\.?\s*A\s*\.?\s*A\s*\.?\s*N\s*\.?", re.IGNORECASE)


def _spoken(text: str, lang: str) -> str:
    """Say the name letter by letter, and split words the voice glues together."""
    text = _clean(text)
    thai = (lang or "").lower().replace("_", "-").startswith("th")
    text = _ACRONYM.sub("เอส เอ เอ เอน" if thai else "S A A N", text)
    if thai:
        text = text.replace("เอสเอเอ็น", "เอส เอ เอ เอน")
        text = text.replace("มิติ", "มิ ติ")
    return re.sub(r"\s+", " ", text).strip()


def _pieces(text: str, limit: int = 220) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    rest = text
    while len(rest) > limit:
        cut = rest.rfind(" ", 0, limit)
        if cut < 40:
            cut = limit
        piece = rest[:cut].strip()
        if piece:
            parts.append(piece)
        rest = rest[cut:].strip()
    if rest:
        parts.append(rest)
    return parts


async def _once(text: str, lang: str, rate: float) -> bytes:
    import edge_tts

    async with _VOICE:
        communicate = edge_tts.Communicate(text, voice_for(lang), rate=_rate(rate))
        audio = bytearray()
        async for message in communicate.stream():
            if message["type"] == "audio":
                audio.extend(message["data"])
        if not audio:
            raise RuntimeError("empty audio")
        return bytes(audio)


async def _best(text: str, lang: str, rate: float, depth: int = 0) -> bytes:
    """One clean clip. A failed clip is retried in order by the reader, not dropped here."""
    return await _once(text, lang, rate)


_CACHE: dict[tuple[str, str, str], bytes] = {}
_CACHE_ORDER: list[tuple[str, str, str]] = []
_INFLIGHT: dict[tuple[str, str, str], asyncio.Task[bytes]] = {}
_CACHE_LIMIT = 80


async def synthesize(text: str, lang: str, rate: float = 1.0) -> bytes:
    cleaned = _spoken(text, lang)
    if not cleaned:
        raise RuntimeError("empty audio")
    key = (cleaned, voice_for(lang), _rate(rate))
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    flight = _INFLIGHT.get(key)
    if flight is not None:
        return await flight
    task = asyncio.create_task(_best(cleaned, lang, rate))
    _INFLIGHT[key] = task
    try:
        audio = await task
    except Exception:
        _INFLIGHT.pop(key, None)
        raise
    _CACHE[key] = audio
    _CACHE_ORDER.append(key)
    while len(_CACHE_ORDER) > _CACHE_LIMIT:
        _CACHE.pop(_CACHE_ORDER.pop(0), None)
    _INFLIGHT.pop(key, None)
    return audio
