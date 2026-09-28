"""Reader and volunteer flows, without a live OCR binary."""

import re
from io import BytesIO

import pytest
from PIL import Image

from app.i18n import STRINGS
from app.ocr import score_transcript, split_text


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SAAN_DATABASE_URL", "sqlite:///" + (tmp_path / "test.db").as_posix())
    monkeypatch.setenv("SAAN_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("SAAN_SEED_DEMO", "false")
    monkeypatch.setenv("SAAN_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("SAAN_GEMINI_API_KEY", "")
    from app.config import get_settings

    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(), follow_redirects=True) as test_client:
        yield test_client
    get_settings.cache_clear()


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match, "csrf token missing"
    return match.group(1)


def _png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (64, 40), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_copy_keys_match():
    assert STRINGS["en"].keys() == STRINGS["th"].keys()
    assert "need_thai_voice" in STRINGS["th"]


def test_ocr_score_prefers_real_words():
    from app.ocr import clean_ocr_text

    assert score_transcript("ความรู้ที่ชัดเจน") > score_transcript("|||###@@@")
    assert score_transcript("knowledge") > score_transcript("")
    assert "การชะลอ" in clean_ocr_text("ก า ร ชะ ล อ")
    assert clean_ocr_text("to access knowledge") == "to access knowledge"


def test_split_text_groups_long_pages():
    page = "\n".join(f"Line {index} of a long page." for index in range(40))
    parts = split_text(page)
    assert len(parts) > 1
    assert split_text("  ") == []
    assert split_text("One\n\nTwo") == ["One", "Two"]


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_roles_are_separated(client):
    _register(client, "reader@example.com", "Reader", "reader")
    denied = client.get("/mission")
    assert denied.status_code == 403
    assert "volunteer" in denied.text.lower() or "อาสา" in denied.text or "Mission control" in denied.text
    client.post("/logout", data={"csrf": _csrf(client.get("/read").text)})
    _register(client, "volunteer@example.com", "Volunteer", "volunteer")
    denied = client.get("/read")
    assert denied.status_code == 403


def test_upload_flag_and_correction(client, monkeypatch):
    from app.ocr import OcrResult

    monkeypatch.setattr(
        "app.services.documents.run_ocr",
        lambda path: OcrResult("Hello world.\n\nSecond paragraph.", "test", 88.0),
    )
    _register(client, "mali@example.com", "Mali", "reader")
    desk = client.get("/read")
    uploaded = client.post(
        "/documents",
        data={"csrf": _csrf(desk.text)},
        files={"image": ("page.png", _png(), "image/png")},
    )
    assert uploaded.status_code == 200
    location = uploaded.url.path
    page = uploaded.text
    for _ in range(8):
        if "Hello world." in page:
            break
        page = client.get(location).text
    assert "Hello world." in page
    assert "The system is 88% confident." in page
    flag = re.search(r'action="(/documents/\d+/snippets/\d+/flag)"', page)
    assert flag
    flagged = client.post(flag.group(1), data={"csrf": _csrf(page), "note": "Last word"})
    assert flagged.status_code == 200
    assert "Sent." in flagged.text or "ส่งแล้ว" in flagged.text

    client.post("/logout", data={"csrf": _csrf(flagged.text)})
    _register(client, "arun@example.com", "Arun", "volunteer")
    mission = client.get("/mission")
    assert "Hello world." in mission.text
    link = re.search(r'href="(/mission/\d+)"', mission.text)
    assert link
    review = client.get(link.group(1))
    claimed = client.post(link.group(1) + "/claim", data={"csrf": _csrf(review.text)})
    assert claimed.status_code == 200
    saved = client.post(
        link.group(1) + "/correct",
        data={"csrf": _csrf(claimed.text), "text": "Hello, world."},
    )
    assert saved.status_code == 200
    assert "25" in saved.text
    assert "First light" in saved.text

    client.post("/logout", data={"csrf": _csrf(saved.text)})
    login = client.get("/login")
    client.post(
        "/login",
        data={"csrf": _csrf(login.text), "email": "mali@example.com", "password": "demo-pass-1", "next": ""},
    )
    library = client.get("/library")
    assert "page.png" in library.text
    again = client.get(location)
    assert "Hello, world." in again.text


def test_speak_requires_login(client):
    response = client.post("/api/speak", json={"text": "สวัสดี", "lang": "th-TH", "rate": 1})
    assert response.status_code == 401


def test_thai_marks_stay_with_their_consonant():
    from app.ocr import clean_ocr_text, repair_thai

    assert repair_thai("ก่ิ") == "กิ่"
    assert repair_thai("สิทธิ์") == "สิทธิ์"
    sentence = "ทุกคนมีสิทธิ์เข้าถึงความรู้อย่างเท่าเทียม"
    assert repair_thai(sentence) == sentence
    assert "กิ่" in clean_ocr_text("ก่ิ")


def test_leaderboard_periods(client):
    _register(client, "board@example.com", "Board", "volunteer")
    page = client.get("/mission")
    assert "Daily" in page.text or "รายวัน" in page.text
    month = client.get("/mission?board=month")
    assert "Monthly" in month.text or "รายเดือน" in month.text
    year = client.get("/mission?board=year")
    assert "Yearly" in year.text or "รายปี" in year.text


def test_bangkok_clock_and_gemini_only(monkeypatch, tmp_path):
    from datetime import datetime, timezone

    from app.config import get_settings
    from app.ocr import run_ocr
    from app.web import format_local

    moment = datetime(2026, 9, 27, 11, 37, tzinfo=timezone.utc)
    assert format_local(moment, "th") == "27 ก.ย. 2026 เวลา 18:37 น."
    assert format_local(datetime(2026, 9, 27, 11, 37), "th") == "27 ก.ย. 2026 เวลา 18:37 น."
    english = format_local(moment, "en")
    assert "18:37" in english
    assert "UTC" not in english

    monkeypatch.setenv("SAAN_GEMINI_API_KEY", "")
    get_settings.cache_clear()
    image = tmp_path / "blank.png"
    Image.new("RGB", (8, 8), "white").save(image, format="PNG")
    with pytest.raises(RuntimeError, match="gemini_missing"):
        run_ocr(image)
    get_settings.cache_clear()


def test_queue_empty_state_is_singular(client):
    _register(client, "queue@example.com", "Queue", "volunteer")
    page = client.get("/mission")
    assert page.text.count("Waiting to be checked") == 1
    assert "Nothing is waiting right now. Thank you for stopping by to help." in page.text
    assert "Edits waiting for a trusted check" not in page.text


def test_about_names_the_developers(client):
    page = client.get("/about")
    assert page.status_code == 200
    assert "Wasana J." in page.text
    assert "Thidaporn S." in page.text
    assert "saan.accessibility@gmail.com" in page.text
    assert "ทุกคนมีสิทธิ์เข้าถึงความรู้อย่างเท่าเทียม" in page.text


def test_language_toggle(client):
    client.post("/prefs/lang", data={"csrf": _csrf(client.get("/").text), "next": "/", "value": "th"})
    thai = client.get("/")
    assert "ทุกคนมีสิทธิ์เข้าถึงความรู้อย่างเท่าเทียม" in thai.text
    assert 'value="th"' in thai.text and 'aria-pressed="true"' in thai.text
    client.post("/prefs/lang", data={"csrf": _csrf(thai.text), "next": "/", "value": "en"})
    english = client.get("/")
    assert "Everyone has an equal right to access knowledge." in english.text


def test_complex_page_goes_to_volunteers(client, monkeypatch):
    from app.ocr import OcrResult

    formula = "Area = \\frac{1}{2}bh\n\n∫ velocity dt"
    monkeypatch.setattr("app.services.documents.run_ocr", lambda path: OcrResult(formula, "test", 40.0))
    _register(client, "reader-formula@example.com", "Formula", "reader")
    desk = client.get("/read")
    uploaded = client.post(
        "/documents",
        data={"csrf": _csrf(desk.text)},
        files={"image": ("formula.png", _png(), "image/png")},
    )
    page = uploaded.text
    for _ in range(8):
        if "complex" in page.lower() or "ตาราง" in page or "formula" in page.lower() or "สูตร" in page:
            break
        page = client.get(uploaded.url.path).text
    assert "สูตร" in page or "formula" in page.lower() or "table" in page.lower() or "ตาราง" in page
    client.post("/logout", data={"csrf": _csrf(page)})
    _register(client, "vol-formula@example.com", "Checker", "volunteer")
    mission = client.get("/mission")
    assert "\\frac" in mission.text or "velocity" in mission.text


def test_image_deletes_after_the_privacy_window(client, monkeypatch):
    from datetime import timedelta

    from app.database import SessionLocal
    from app.models import Document, utcnow
    from app.ocr import OcrResult
    from app.services.documents import purge_expired_images, upload_path

    monkeypatch.setattr(
        "app.services.documents.run_ocr",
        lambda path: OcrResult("A plain sentence for the privacy test.", "test", 90.0),
    )
    _register(client, "reader-privacy@example.com", "Privacy", "reader")
    desk = client.get("/read")
    uploaded = client.post(
        "/documents",
        data={"csrf": _csrf(desk.text)},
        files={"image": ("private.png", _png(), "image/png")},
    )
    page = uploaded.text
    for _ in range(8):
        if "A plain sentence" in page:
            break
        page = client.get(uploaded.url.path).text
    assert "A plain sentence" in page
    db = SessionLocal()
    try:
        document = db.query(Document).filter(Document.original_filename == "private.png").one()
        path = upload_path(document.stored_name)
        assert path.exists()
        assert document.image_purge_at is not None
        document.image_purge_at = utcnow() - timedelta(hours=1)
        db.commit()
        assert purge_expired_images(db) == 1
        assert not path.exists()
        db.refresh(document)
        assert document.image_purged_at is not None
    finally:
        db.close()


def test_large_rewrite_waits_for_a_trusted_volunteer(client, monkeypatch):
    from app.ocr import OcrResult

    monkeypatch.setattr(
        "app.services.documents.run_ocr",
        lambda path: OcrResult("Hello world.\n\nSecond paragraph.", "test", 88.0),
    )
    _register(client, "reader-trust@example.com", "Reader Trust", "reader")
    desk = client.get("/read")
    uploaded = client.post(
        "/documents",
        data={"csrf": _csrf(desk.text)},
        files={"image": ("trust.png", _png(), "image/png")},
    )
    page = uploaded.text
    for _ in range(8):
        if "Hello world." in page:
            break
        page = client.get(uploaded.url.path).text
    flag = re.search(r'action="(/documents/\d+/snippets/\d+/flag)"', page)
    flagged = client.post(flag.group(1), data={"csrf": _csrf(page)})
    client.post("/logout", data={"csrf": _csrf(flagged.text)})
    _register(client, "new-volunteer@example.com", "New Volunteer", "volunteer")
    mission = client.get("/mission")
    link = re.search(r'href="(/mission/\d+)"', mission.text)
    review = client.get(link.group(1))
    claimed = client.post(link.group(1) + "/claim", data={"csrf": _csrf(review.text)})
    saved = client.post(
        link.group(1) + "/correct",
        data={"csrf": _csrf(claimed.text), "text": "completely unrelated vandal text with no shared words at all"},
    )
    assert "held" in saved.text.lower() or "การแก้นี้" in saved.text or "trusted volunteer" in saved.text.lower()
    client.post("/logout", data={"csrf": _csrf(saved.text)})
    login = client.get("/login")
    client.post(
        "/login",
        data={"csrf": _csrf(login.text), "email": "reader-trust@example.com", "password": "demo-pass-1", "next": ""},
    )
    again = client.get(uploaded.url.path)
    assert "Hello world." in again.text
    assert "unrelated vandal" not in again.text


def test_scan_confidence_sentence_and_parser():
    from app.i18n import STRINGS
    from app.ocr import _clamp_percent, _parse_gemini_reading, estimate_confidence

    assert STRINGS["th"]["scan_confidence"].format(n=86) == "ระบบมั่นใจ 86%"
    assert STRINGS["en"]["scan_confidence"].format(n=86) == "The system is 86% confident."
    text, score = _parse_gemini_reading('{"text": "สวัสดี\\n\\nโลก", "confidence": 86.6}')
    assert text == "สวัสดี\n\nโลก"
    assert score == 87
    plain, missing = _parse_gemini_reading("สวัสดีครับ")
    assert plain == "สวัสดีครับ"
    assert missing is None
    assert _clamp_percent(140) == 100
    assert _clamp_percent(-4) == 0
    assert _clamp_percent(True) is None
    assert 20 <= estimate_confidence("A clear printed sentence about access.") <= 90


def test_repeated_phrase_is_spoken_once(monkeypatch):
    import asyncio

    from app import speech

    speech._CACHE.clear()
    speech._CACHE_ORDER.clear()
    speech._INFLIGHT.clear()
    calls = {"n": 0}

    async def fake(text, lang, rate, depth=0):
        calls["n"] += 1
        return b"mp3"

    monkeypatch.setattr(speech, "_best", fake)
    first = asyncio.run(speech.synthesize("hello", "en-US", 1))
    second = asyncio.run(speech.synthesize("hello", "en-US", 1))
    assert first == second == b"mp3"
    assert calls["n"] == 1
    speech._CACHE.clear()
    speech._CACHE_ORDER.clear()


def test_spoken_name_is_spelled_and_miti_is_split():
    from app.speech import _spoken

    assert _spoken("S.A.A.N. เปิดมิติใหม่", "th-TH") == "เอส เอ เอ เอน เปิดมิ ติใหม่"
    assert _spoken("Welcome to S.A.A.N.", "en-US") == "Welcome to S A A N"


def test_welcome_voice_is_the_fixed_greeting(client, monkeypatch):
    async def fake_voice(text, lang, rate):
        assert "เอส เอ เอ เอน" in text
        assert "เท่าเทียม" in text
        assert lang == "th-TH"
        return b"welcome-audio"

    monkeypatch.setattr("app.routers.api.synthesize", fake_voice)
    monkeypatch.setattr("app.routers.api._welcome_audio", {})
    heard = client.get("/api/welcome?lang=th")
    assert heard.status_code == 200
    assert heard.headers["content-type"].startswith("audio/mpeg")
    assert heard.content == b"welcome-audio"
    page = client.get("/")
    assert "Play the welcome" in page.text
    assert "Read this page" in page.text
    assert "A−" in page.text
    client.post("/prefs/lang", data={"csrf": _csrf(page.text), "next": "/", "value": "th"})
    thai = client.get("/")
    assert "ยินดีต้อนรับสู่ S.A.A.N. แพลตฟอร์มเทคโนโลยีเพื่อการเข้าถึงการเรียนรู้อย่างเท่าเทียม" in thai.text


def test_rejects_non_images(client):
    _register(client, "reader2@example.com", "Reader Two", "reader")
    page = client.get("/read")
    response = client.post(
        "/documents",
        data={"csrf": _csrf(page.text)},
        files={"image": ("notes.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    disguised = client.post(
        "/documents",
        data={"csrf": _csrf(page.text)},
        files={"image": ("page.png", b"<script>alert(1)</script>", "image/png")},
    )
    assert disguised.status_code == 400


def test_new_profanity_is_blocked_but_printed_words_can_stay():
    from app.moderation import abuse_introduced
    from app.limits import allow

    assert abuse_introduced("Hello world.", "Hello, world.") is False
    assert abuse_introduced("ความรู้ที่ชัดเจน", "ความรู้ที่ชัดเจน") is False
    assert abuse_introduced("the word fuck is printed", "the word fuck is printed") is False
    assert abuse_introduced("Hello world.", "fuck off") is True
    assert abuse_introduced("Hello world.", "<script>alert(1)</script>") is True
    assert all(allow("unit-upload", 2, 60) for _ in range(2))
    assert allow("unit-upload", 2, 60) is False


def test_profanity_suspends_the_account(client, monkeypatch):
    from app.ocr import OcrResult

    monkeypatch.setattr(
        "app.services.documents.run_ocr",
        lambda path: OcrResult("Hello world.", "test", 88.0),
    )
    _register(client, "kind@example.com", "Kind Reader", "reader")
    desk = client.get("/read")
    uploaded = client.post(
        "/documents",
        data={"csrf": _csrf(desk.text)},
        files={"image": ("page.png", _png(), "image/png")},
    )
    page = uploaded.text
    for _ in range(8):
        if "Hello world." in page:
            break
        page = client.get(uploaded.url.path).text
    flag = re.search(r'action="(/documents/\d+/snippets/\d+/flag)"', page)
    flagged = client.post(flag.group(1), data={"csrf": _csrf(page)})
    client.post("/logout", data={"csrf": _csrf(flagged.text)})
    _register(client, "rude@example.com", "Rude", "volunteer")
    mission = client.get("/mission")
    link = re.search(r'href="(/mission/\d+)"', mission.text)
    review = client.get(link.group(1))
    claimed = client.post(link.group(1) + "/claim", data={"csrf": _csrf(review.text)})
    blocked = client.post(
        link.group(1) + "/correct",
        data={"csrf": _csrf(claimed.text), "text": "fuck off"},
    )
    assert blocked.status_code == 403
    assert "suspended" in blocked.text.lower() or "ระงับ" in blocked.text
    assert "fuck off" not in blocked.text
    login = client.get("/login")
    again = client.post(
        "/login",
        data={"csrf": _csrf(login.text), "email": "rude@example.com", "password": "demo-pass-1", "next": ""},
    )
    assert again.status_code == 403
    register = client.get("/register")
    named = client.post(
        "/register",
        data={
            "csrf": _csrf(register.text),
            "email": "name@example.com",
            "display_name": "fuck",
            "password": "demo-pass-1",
            "role": "reader",
        },
    )
    assert named.status_code == 400


def _register(client, email: str, name: str, role: str) -> None:
    page = client.get("/register")
    response = client.post(
        "/register",
        data={
            "csrf": _csrf(page.text),
            "email": email,
            "display_name": name,
            "password": "demo-pass-1",
            "role": role,
        },
    )
    assert response.status_code == 200
