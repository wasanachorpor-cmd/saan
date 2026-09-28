"""Page reading through the Gemini API, plus Thai text cleanup."""

from __future__ import annotations

import base64
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

_THAI = re.compile(r"[\u0E00-\u0E7F]")
_LATIN = re.compile(r"[A-Za-z]")
_LETTER = re.compile(r"[\u0E00-\u0E7FA-Za-z0-9]")
_JUNK = re.compile(r"[^\s\u0E00-\u0E7FA-Za-z0-9.,;:'\"!?()%+\-–—/«»“”‘’…]")


@dataclass
class OcrResult:
    text: str
    engine: str
    confidence: float | None


def looks_complex(text: str, confidence: float | None = None) -> str | None:
    """Return a layout kind when the page is a table, chart, or formula OCR cannot trust."""
    sample = text or ""
    if re.search(r"[∫∑√≈≠≤≥±∞∆∂∇]|\\[a-zA-Z]{2,}|\$[^$\n]{2,}\$", sample):
        return "formula"
    lines = [line.strip() for line in sample.splitlines() if line.strip()]
    pipe_lines = sum(1 for line in lines if line.count("|") >= 2)
    if len(lines) >= 3 and pipe_lines >= 2:
        return "table"
    letters = len(_LETTER.findall(sample))
    symbols = len(re.findall(r"[\\^_=<>{}[\]~#*]", sample))
    if letters >= 8 and symbols / letters >= 0.28:
        return "formula"
    if confidence is not None and confidence < 35 and letters >= 8 and symbols >= 6:
        return "chart"
    return None


def text_language(text: str) -> str:
    thai = len(_THAI.findall(text))
    latin = len(_LATIN.findall(text))
    if thai > latin and thai > 0:
        return "th"
    if latin > 0 and latin >= thai:
        return "en"
    if thai > 0:
        return "th"
    return "und"


def split_text(text: str) -> list[str]:
    """Break a page into volunteer-sized paragraphs."""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    if not cleaned:
        return []
    parts = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    if len(parts) == 1 and len(parts[0]) > 900:
        lines = [line.strip() for line in parts[0].split("\n") if line.strip()]
        grouped: list[str] = []
        buffer = ""
        for line in lines:
            if buffer and len(buffer) + len(line) > 500:
                grouped.append(buffer)
                buffer = line
            else:
                buffer = f"{buffer}\n{line}".strip()
        if buffer:
            grouped.append(buffer)
        parts = grouped
    return parts[:40]


_EASYOCR = None


def run_ocr(path: Path) -> OcrResult:
    """Send the page photo to Gemini and return the transcription."""
    settings = get_settings()
    if not settings.gemini_api_key.strip():
        raise RuntimeError("gemini_missing")
    try:
        return _gemini(path)
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001 - hide the key, keep a short reason
        log.warning("Gemini reading failed: %s", _public_error(exc))
        raise RuntimeError(_public_error(exc)) from exc


def _choose_reading(found: list[OcrResult]) -> OcrResult:
    """Keep a very confident page reading. Otherwise prefer the photo reader."""
    by_engine = {item.engine: item for item in found}
    easy = by_engine.get("easyocr")
    tess = by_engine.get("tesseract")
    if easy is None or tess is None:
        return max(found, key=lambda item: score_transcript(item.text))
    tess_score = score_transcript(tess.text)
    easy_score = score_transcript(easy.text)
    if (tess.confidence or 0) >= 90 and tess_score >= easy_score * 0.9:
        return tess
    if easy_score >= 20:
        return easy
    return tess


def _public_error(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    text = re.sub(r"(key=)[^&\s]+", r"\1***", text, flags=re.I)
    text = re.sub(r"AIza[0-9A-Za-z\-_]{8,}", "***", text)
    return text[:300]


def _is_thai_fragment(part: str) -> bool:
    """One Thai letter or one syllable, not a whole word and not Latin."""
    if re.search(r"[A-Za-z0-9]", part) or not _THAI.search(part):
        return False
    bases = len(re.findall(r"[\u0E01-\u0E2E]", part))
    return bases <= 1


def _collapse_spaced_thai(line: str) -> str:
    """Join Thai letters that the engine split one by one. Leave real words alone."""
    parts = [part for part in re.split(r" +", line.strip()) if part]
    if len(parts) < 4:
        return line.strip()
    fragments = sum(1 for part in parts if _is_thai_fragment(part))
    if fragments < len(parts) * 0.45:
        return line.strip()
    grouped: list[str] = []
    buffer = ""
    for part in parts:
        if _is_thai_fragment(part):
            buffer += part
            continue
        if buffer:
            grouped.append(buffer)
            buffer = ""
        grouped.append(part)
    if buffer:
        grouped.append(buffer)
    return " ".join(grouped)


def _drop_noise_tokens(line: str) -> str:
    kept: list[str] = []
    for token in line.split(" "):
        if not token:
            continue
        digits = len(re.findall(r"[0-9๐-๙]", token))
        letters = len(re.findall(r"[A-Za-z\u0E01-\u0E2E]", token))
        if digits and letters and digits >= letters and len(token) < 12:
            continue
        kept.append(token)
    return " ".join(kept).strip()


_THAI_BELOW = set("ุู")
_THAI_ABOVE = set("ัิีึื็ํ")
_THAI_TONE = set("่้๊๋")


def _mark_level(char: str) -> int:
    if char in _THAI_BELOW:
        return 1
    if char in _THAI_ABOVE:
        return 2
    if char in _THAI_TONE:
        return 3
    if char == "์":
        return 4
    return 0


def repair_thai(text: str) -> str:
    """Put Thai vowels and tone marks back into the order fonts can draw."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFC", text).replace("ํา", "ำ").replace("าํ", "ำ")
    chars = list(normalized)
    out: list[str] = []
    index = 0
    while index < len(chars):
        char = chars[index]
        if _mark_level(char) == 0 and "\u0e01" <= char <= "\u0e2e":
            index += 1
            marks: list[str] = []
            while index < len(chars) and _mark_level(chars[index]) > 0:
                marks.append(chars[index])
                index += 1
            marks.sort(key=_mark_level)
            out.append(char)
            out.extend(marks)
            continue
        out.append(char)
        index += 1
    return "".join(out)


def clean_ocr_text(text: str) -> str:
    """Keep real letters and paragraph breaks. Drop symbol-only noise."""
    cleaned = repair_thai(text).replace("\x0c", "").replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for line in cleaned.split("\n"):
        line = _drop_noise_tokens(_collapse_spaced_thai(re.sub(r"[ \t]{2,}", " ", line)))
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue
        if not _LETTER.search(line):
            continue
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def score_transcript(text: str) -> float:
    """Prefer a transcription full of real letters over symbol soup."""
    cleaned = clean_ocr_text(text)
    if not cleaned:
        return -1.0
    letters = len(_LETTER.findall(cleaned))
    junk = len(_JUNK.findall(cleaned))
    return float(letters - junk * 4)


def _load_gray(path: Path):
    """Load a page and honor the photo's stored rotation."""
    try:
        import cv2
        import numpy as np
        from PIL import Image, ImageOps
    except ImportError:
        return None
    try:
        with Image.open(path) as opened:
            rgb = ImageOps.exif_transpose(opened).convert("RGB")
        array = np.array(rgb)
        return cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
    except Exception:  # noqa: BLE001
        data = np.fromfile(str(path), dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if image is None:
            return None
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _rotate_bound(image, angle: float):
    import cv2
    import numpy as np

    height, width = image.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    cosine = abs(matrix[0, 0])
    sine = abs(matrix[0, 1])
    bound_w = int(height * sine + width * cosine)
    bound_h = int(height * cosine + width * sine)
    matrix[0, 2] += bound_w / 2.0 - center[0]
    matrix[1, 2] += bound_h / 2.0 - center[1]
    border = int(np.median(image)) if image.size else 255
    return cv2.warpAffine(
        image,
        matrix,
        (bound_w, bound_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=border,
    )


def _osd_turn(gray, pytesseract):
    """Turn a sideways page upright when Tesseract is sure of the angle."""
    import cv2
    from PIL import Image

    height, width = gray.shape[:2]
    probe = gray
    longest = max(height, width)
    if longest > 1200:
        scale = 1200 / float(longest)
        probe = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    try:
        osd = pytesseract.image_to_osd(Image.fromarray(probe), config="--psm 0")
    except Exception:  # noqa: BLE001
        return gray, False
    rotate = 0
    confidence = 0.0
    for line in osd.splitlines():
        if line.startswith("Rotate:"):
            rotate = int(float(line.split(":", 1)[1].strip()))
        elif line.startswith("Orientation confidence:"):
            confidence = float(line.split(":", 1)[1].strip())
    if confidence < 1.5 or rotate not in (90, 180, 270):
        return gray, False
    turns = {
        90: cv2.ROTATE_90_CLOCKWISE,
        180: cv2.ROTATE_180,
        270: cv2.ROTATE_90_COUNTERCLOCKWISE,
    }
    return cv2.rotate(gray, turns[rotate]), True


def _quarter_turns(gray, pytesseract, lang: str):
    """Pick the quarter turn whose text actually reads as words."""
    import cv2
    from PIL import Image

    height, width = gray.shape[:2]
    longest = max(height, width)
    scale = 800 / float(longest) if longest > 800 else 1.0
    probe = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray
    turns = (None, cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE)
    best_index = 0
    best_score = -1.0
    for index, turn in enumerate(turns):
        sample = probe if turn is None else cv2.rotate(probe, turn)
        raw = _read_once(pytesseract, Image.fromarray(sample), lang, 6) or ""
        score = score_transcript(raw)
        if score > best_score:
            best_score = score
            best_index = index
    if best_index == 0:
        return gray
    return cv2.rotate(gray, turns[best_index])


def _deskew(gray):
    """Level text that sits a few degrees off horizontal."""
    import cv2
    import numpy as np

    height, width = gray.shape[:2]
    longest = max(height, width)
    scale = 700 / float(longest) if longest > 700 else 1.0
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray
    _level, ink = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    best_angle = 0.0
    best_score = -1.0
    for step in range(-16, 17):
        angle = step * 0.5
        turned = ink if angle == 0 else _rotate_bound(ink, angle)
        rows = np.sum(turned > 0, axis=1).astype("float64")
        score = float(np.var(rows)) if rows.size else 0.0
        if score > best_score:
            best_score = score
            best_angle = angle
    if abs(best_angle) < 0.4:
        return gray
    return _rotate_bound(gray, best_angle)


def _candidate_images(path: Path, pytesseract, lang: str) -> list:
    """Straighten the page, then offer a gentle gray and one black-and-white copy."""
    try:
        import cv2
        from PIL import Image
    except ImportError:
        return []
    gray = _load_gray(path)
    if gray is None:
        return []
    gray, turned = _osd_turn(gray, pytesseract)
    if not turned:
        gray = _quarter_turns(gray, pytesseract, lang)
    gray = _deskew(gray)
    _height, width = gray.shape[:2]
    if width < 1800:
        scale = 1800 / float(width)
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    soft = cv2.bilateralFilter(clahe.apply(gray), 5, 40, 40)
    _threshold, otsu = cv2.threshold(soft, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return [Image.fromarray(soft), Image.fromarray(otsu)]


def _easyocr(path: Path) -> OcrResult:
    """Local reader that handles Thai and English on photos better than a single pass."""
    global _EASYOCR
    try:
        import easyocr
    except ImportError as exc:
        raise RuntimeError("easyocr is not installed") from exc
    if _EASYOCR is None:
        _EASYOCR = easyocr.Reader(["th", "en"], gpu=False, verbose=False)
    chunks = _EASYOCR.readtext(str(path), detail=1, paragraph=False)
    text, confidence = _lines_from_easy(chunks)
    if not text:
        raise RuntimeError("ocr_empty")
    return OcrResult(text=text, engine="easyocr", confidence=confidence)


def _lines_from_easy(chunks) -> tuple[str, float | None]:
    rows = []
    for box, raw, confidence in chunks:
        word = (raw or "").strip()
        if not word:
            continue
        tops = [point[1] for point in box]
        lefts = [point[0] for point in box]
        top = min(tops)
        height = max(tops) - top
        rows.append((top, height, min(lefts), word, float(confidence)))
    if not rows:
        return "", None
    rows.sort()
    lines: list[list[tuple[float, str, float]]] = []
    current: list[tuple[float, str, float]] = []
    band: float | None = None
    for top, height, left, word, confidence in rows:
        if band is None or abs(top - band) <= max(14.0, height * 0.65):
            current.append((left, word, confidence))
            band = top if band is None else band * 0.7 + top * 0.3
        else:
            lines.append(current)
            current = [(left, word, confidence)]
            band = top
    if current:
        lines.append(current)
    texts: list[str] = []
    scores: list[float] = []
    for line in lines:
        line.sort()
        texts.append(" ".join(word for _left, word, _score in line))
        scores.extend(score for _left, _word, score in line)
    if scores and max(scores) <= 1:
        mean = round(sum(scores) / len(scores) * 100, 1)
    elif scores:
        mean = round(sum(scores) / len(scores), 1)
    else:
        mean = None
    return clean_ocr_text("\n".join(texts)), mean


def _tesseract_cmd() -> str | None:
    settings = get_settings()
    if settings.tesseract_cmd:
        return settings.tesseract_cmd
    windows = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    if windows.exists():
        return str(windows)
    return None


def _installed_langs(pytesseract) -> list[str]:
    try:
        installed = set(pytesseract.get_languages(config=""))
    except Exception:  # noqa: BLE001
        return ["eng"]
    if "tha" in installed and "eng" in installed:
        return ["tha+eng", "tha", "eng"]
    if "tha" in installed:
        return ["tha"]
    return ["eng"]


def _read_once(pytesseract, image, lang: str, psm: int) -> str | None:
    configs = (
        f"--oem 1 --psm {psm} -c preserve_interword_spaces=1",
        f"--psm {psm}",
    )
    for config in configs:
        try:
            return pytesseract.image_to_string(image, lang=lang, config=config) or ""
        except Exception:  # noqa: BLE001
            continue
    return None


def _tesseract(path: Path) -> OcrResult:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("pytesseract or Pillow is not installed") from exc

    command = _tesseract_cmd()
    if command:
        pytesseract.pytesseract.tesseract_cmd = command

    langs = _installed_langs(pytesseract)
    primary = langs[0]
    images = _candidate_images(path, pytesseract, primary)
    if not images:
        images = [Image.open(path)]

    found: list[tuple[str, object, str]] = []
    for psm in (6, 3):
        raw = _read_once(pytesseract, images[0], primary, psm)
        if raw:
            found.append((raw, images[0], primary))
    if len(images) > 1:
        raw = _read_once(pytesseract, images[1], primary, 6)
        if raw:
            found.append((raw, images[1], primary))
    if not found:
        raise RuntimeError("ocr_empty")

    best_text, best_image, best_lang = max(found, key=lambda item: score_transcript(item[0]))
    if "tha" in langs and "eng" in langs:
        thai = len(_THAI.findall(best_text))
        latin = len(_LATIN.findall(best_text))
        extra = "tha" if thai >= latin else "eng"
        retry = _read_once(pytesseract, best_image, extra, 6)
        if retry and score_transcript(retry) > score_transcript(best_text) + 2:
            best_text, best_lang = retry, extra

    cleaned = clean_ocr_text(best_text)
    if not cleaned:
        raise RuntimeError("ocr_empty")
    confidence = _mean_confidence(pytesseract, best_image, best_lang)
    return OcrResult(text=cleaned, engine="tesseract", confidence=confidence)


def _mean_confidence(pytesseract, image, lang: str) -> float | None:
    try:
        from pytesseract import Output

        data = pytesseract.image_to_data(
            image,
            lang=lang,
            output_type=Output.DICT,
            config="--oem 1 --psm 6 -c preserve_interword_spaces=1",
        )
    except Exception:  # noqa: BLE001
        return None
    scores = []
    for raw in data.get("conf", []):
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            scores.append(value)
    if not scores:
        return None
    return round(sum(scores) / len(scores), 1)


_GEMINI_PROMPT = (
    "Transcribe the printed words on this page in reading order, top to bottom. "
    "Skip photographs, drawings, icons, and decorative art. Do not describe pictures "
    "and do not invent captions. If a figure has printed words or a caption, "
    "transcribe those words in their own paragraph. "
    "Keep Thai vowel marks and tone markers on the correct consonants, "
    "in Unicode order: consonant, then lower vowel, then upper vowel, then tone mark. "
    "Keep numbers, punctuation, and line breaks exactly as printed. "
    "Do not translate, summarize, omit printed words, or add words that are not printed. "
    "Separate paragraphs with a blank line. "
    "Return a JSON object with two fields and no other text. "
    "text is the transcription. "
    "confidence is an integer from 0 to 100 for how sure you are that the transcription "
    "matches the printed words. Use 100 only when every word is sharp and complete. "
    "Lower it when words are blurry, cropped, covered, or guessed."
)

_GEMINI_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "text": {"type": "STRING"},
        "confidence": {"type": "INTEGER"},
    },
    "required": ["text", "confidence"],
}

_GEMINI_FALLBACKS = ("gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.1-flash-lite")


def _gemini_models() -> list[str]:
    chosen = get_settings().gemini_model.strip() or _GEMINI_FALLBACKS[0]
    models = [chosen]
    for name in _GEMINI_FALLBACKS:
        if name not in models:
            models.append(name)
    return models


def _gemini(path: Path) -> OcrResult:
    last_busy = False
    for model in _gemini_models():
        for attempt in range(3):
            try:
                return _gemini_once(path, model)
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code in {404, 429, 500, 503}:
                    last_busy = code != 404
                    log.warning("Gemini %s returned %s on attempt %s", model, code, attempt + 1)
                    if code in {429, 500, 503} and attempt < 2:
                        time.sleep(1.6 * (attempt + 1))
                        continue
                    break
                raise
            except RuntimeError:
                raise
    raise RuntimeError("gemini_busy" if last_busy else "ocr_empty")


def _clamp_percent(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return float(int(round(max(0.0, min(100.0, number)))))


def estimate_confidence(text: str) -> float:
    """A cautious percent when the reader does not report its own score."""
    cleaned = clean_ocr_text(text)
    letters = len(_LETTER.findall(cleaned))
    if letters <= 0:
        return 20.0
    junk = len(_JUNK.findall(cleaned))
    score = 88.0 - min(40.0, (junk / letters) * 160.0)
    if letters < 20:
        score -= 15
    if looks_complex(cleaned):
        score -= 18
    return float(int(round(max(20.0, min(90.0, score)))))


def _json_object(text: str) -> dict | None:
    candidate = text.strip()
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _parse_gemini_reading(raw: str) -> tuple[str, float | None]:
    """Split a model reply into transcription text and an optional percent."""
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    payload = _json_object(cleaned)
    if payload is None or "text" not in payload:
        return cleaned, None
    return str(payload.get("text") or "").strip(), _clamp_percent(payload.get("confidence"))


def _candidate_text(body: dict) -> str:
    candidates = body.get("candidates") or []
    if not candidates:
        raise RuntimeError("ocr_empty")
    parts = ((candidates[0].get("content") or {}).get("parts")) or []
    texts: list[str] = []
    for part in parts:
        if not isinstance(part, dict) or part.get("thought"):
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            texts.append(text.strip())
    if not texts:
        raise RuntimeError("ocr_empty")
    for text in reversed(texts):
        if text.lstrip().startswith("{") or '"text"' in text:
            return text
    return "\n".join(texts)


def _gemini_once(path: Path, model: str) -> OcrResult:
    try:
        return _gemini_request(path, model, structured=True)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 400:
            raise
        log.warning("Gemini %s rejected a confidence score, retrying plain text", model)
        return _gemini_request(path, model, structured=False)


def _gemini_request(path: Path, model: str, structured: bool) -> OcrResult:
    suffix = path.suffix.lower()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(
        suffix, "image/jpeg"
    )
    config: dict = {"temperature": 0}
    if structured:
        config["responseMimeType"] = "application/json"
        config["responseSchema"] = _GEMINI_SCHEMA
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": _GEMINI_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": mime,
                            "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": config,
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    response = httpx.post(
        url,
        headers={"x-goog-api-key": get_settings().gemini_api_key.strip()},
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    text, confidence = _parse_gemini_reading(_candidate_text(response.json()))
    text = clean_ocr_text(text)
    if not text:
        raise RuntimeError("ocr_empty")
    if confidence is None:
        confidence = estimate_confidence(text)
    return OcrResult(text=text, engine="gemini", confidence=confidence)
