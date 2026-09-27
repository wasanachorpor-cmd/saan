"""Spoken audio for languages the browser cannot pronounce."""

from __future__ import annotations

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


async def synthesize(text: str, lang: str, rate: float = 1.0) -> bytes:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice_for(lang), rate=_rate(rate))
    audio = bytearray()
    async for message in communicate.stream():
        if message["type"] == "audio":
            audio.extend(message["data"])
    if not audio:
        raise RuntimeError("empty audio")
    return bytes(audio)
