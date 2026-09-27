"""Demo accounts and a welcome page that already needs proofreading."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Document, Snippet, User
from app.ocr import text_language
from app.security import hash_password

log = logging.getLogger(__name__)

DEMO_PASSWORD = "demo1234"
WELCOME_FILE = "welcome-sample.png"

# The stored extraction intentionally misses two words so the queue is real work.
SEEDED_PARAGRAPHS = [
    ("S.A.A.N.", "extracted", None),
    (
        "Everyone has an equal right to access knowlege.",
        "flagged",
        "The last word sounded wrong.",
    ),
    ("ทุกคนมีสิทธิ์เข้าถึงความรู้อย่างเท่าเทียม", "extracted", None),
    (
        "This sentence is printed clearty so a volunteer can correct the extraction.",
        "flagged",
        "One word in the first line sounded wrong.",
    ),
]


def _font(size: int):
    candidates = [
        r"C:\Windows\Fonts\leelawui.ttf",
        r"C:\Windows\Fonts\LeelaUIb.ttf",
        r"C:\Windows\Fonts\tahoma.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def build_welcome_image(path: Path) -> None:
    image = Image.new("RGB", (1400, 1800), "#FFFEFB")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((70, 70, 1330, 1730), radius=28, outline="#0A1128", width=3)
    title = _font(72)
    body = _font(46)
    y = 180
    blocks = [
        ("S.A.A.N.", title, 120),
        ("Everyone has an equal right", body, 90),
        ("to access knowledge.", body, 140),
        ("ทุกคนมีสิทธิ์เข้าถึงความรู้อย่างเท่าเทียม", body, 150),
        ("This sentence is printed clearly", body, 90),
        ("so a volunteer can correct", body, 90),
        ("the extraction.", body, 90),
    ]
    for line, font, gap in blocks:
        draw.text((140, y), line, fill="#0A1128", font=font)
        y += gap
    image.save(path, "PNG")


def seed(db: Session) -> None:
    if not get_settings().seed_demo:
        return
    reader = _ensure_user(db, "reader@saan.local", "Demo Reader", "reader")
    _ensure_user(db, "volunteer@saan.local", "Demo Volunteer", "volunteer")
    existing = (
        db.query(Document)
        .filter(Document.owner_id == reader.id, Document.stored_name == WELCOME_FILE)
        .one_or_none()
    )
    if existing:
        return
    path = get_settings().resolved_upload_dir() / WELCOME_FILE
    if not path.exists():
        build_welcome_image(path)
    from app.models import utcnow

    document = Document(
        owner_id=reader.id,
        original_filename="welcome-page.png",
        stored_name=WELCOME_FILE,
        status="flagged",
        engine="demo",
        confidence=71.0,
    )
    db.add(document)
    db.flush()
    for index, (text, status, note) in enumerate(SEEDED_PARAGRAPHS):
        db.add(
            Snippet(
                document_id=document.id,
                sequence=index,
                original_text=text,
                current_text=text,
                confidence=62.0 if status == "flagged" else 96.0,
                language=text_language(text),
                status=status,
                flag_note=note,
                flagged_at=utcnow() if status == "flagged" else None,
            )
        )
    db.commit()
    log.info("Seeded demo accounts and a welcome page")


def _ensure_user(db: Session, email: str, name: str, role: str) -> User:
    found = db.query(User).filter(User.email == email).one_or_none()
    if found:
        if role == "volunteer" and (found.trust or 0) < 90:
            found.trust = 90
            db.commit()
        return found
    user = User(
        email=email,
        display_name=name,
        password_hash=hash_password(DEMO_PASSWORD),
        role=role,
        points=0,
        trust=90 if role == "volunteer" else 50,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
