"""Volunteer queue, claims, corrections, and standings."""

from __future__ import annotations

import re
from datetime import timedelta
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from app.errors import AppError
from app.moderation import abuse_introduced, suspend
from app.models import EditHistory, Snippet, User, utcnow
from app.services.badges import award_new, next_correction_badge, progress
from app.services.documents import recompute_document

CLAIM_WINDOW = timedelta(minutes=20)
TRUST_MODERATE = 70
CRITICAL_RATIO = 0.5


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def change_ratio(old: str, new: str) -> float:
    left, right = normalize(old), normalize(new)
    if not left and not right:
        return 0.0
    return 1 - SequenceMatcher(None, left, right).ratio()


def is_critical_edit(old: str, new: str, trust: int) -> bool:
    """Large, shrinking, or linked rewrites from a newer volunteer wait for review."""
    if trust < 20:
        return True
    left, right = normalize(old), normalize(new)
    if re.search(r"https?://|www\.", right, re.I):
        return True
    if len(left) >= 40 and len(right) < max(8, int(len(left) * 0.35)):
        return True
    return change_ratio(left, right) >= CRITICAL_RATIO


def _counts(db: Session, user: User) -> tuple[int, int]:
    rows = (
        db.query(EditHistory.previous_text, EditHistory.new_text)
        .filter(EditHistory.volunteer_id == user.id)
        .all()
    )
    corrections = sum(1 for previous, new in rows if normalize(previous) != normalize(new))
    confirms = sum(1 for previous, new in rows if normalize(previous) == normalize(new))
    return corrections, confirms


def queue(db: Session) -> list[Snippet]:
    return (
        db.query(Snippet)
        .filter(Snippet.status.in_(("flagged", "in_review")))
        .order_by(Snippet.flagged_at.asc())
        .all()
    )


def get_snippet(db: Session, snippet_id: int) -> Snippet:
    snippet = db.get(Snippet, snippet_id)
    if snippet is None:
        raise AppError("not_found", 404)
    return snippet


def claim_state(snippet: Snippet, user: User) -> str:
    """Return edit, take, locked, or closed for the current volunteer."""
    if snippet.status not in {"flagged", "in_review"}:
        return "closed"
    if snippet.claimed_by_id is None or snippet.status == "flagged":
        return "take"
    if snippet.claimed_by_id == user.id:
        return "edit"
    if snippet.claimed_at and snippet.claimed_at < utcnow() - CLAIM_WINDOW:
        return "take"
    return "locked"


def claim(db: Session, user: User, snippet_id: int) -> Snippet:
    if user.role != "volunteer":
        raise AppError("forbidden_reader", 403)
    snippet = get_snippet(db, snippet_id)
    state = claim_state(snippet, user)
    if state == "closed":
        raise AppError("unflagged_block", 400)
    if state == "locked":
        raise AppError("locked", 409)
    snippet.claimed_by_id = user.id
    snippet.claimed_at = utcnow()
    snippet.status = "in_review"
    snippet.document.status = "flagged"
    snippet.document.updated_at = utcnow()
    db.commit()
    db.refresh(snippet)
    return snippet


def correct(db: Session, user: User, snippet_id: int, new_text: str) -> tuple[int, list[str]]:
    if user.role != "volunteer":
        raise AppError("forbidden_reader", 403)
    snippet = get_snippet(db, snippet_id)
    text = (new_text or "").strip()
    if not text:
        raise AppError("empty_text", 400)
    if len(text) > 20_000:
        raise AppError("text_too_long", 400)
    if snippet.status not in {"flagged", "in_review"}:
        raise AppError("unflagged_block", 400)
    if snippet.claimed_by_id != user.id:
        raise AppError("claim_first", 403)
    if abuse_introduced(snippet.current_text, text):
        suspend(user)
        db.commit()
        raise AppError("account_suspended", 403)
    if normalize(text) == normalize(snippet.current_text):
        duplicate = (
            db.query(EditHistory)
            .filter(
                EditHistory.snippet_id == snippet.id,
                EditHistory.volunteer_id == user.id,
                EditHistory.new_text == snippet.current_text,
            )
            .first()
        )
        if duplicate and normalize(duplicate.previous_text) == normalize(snippet.current_text):
            raise AppError("already_saved", 400)

    changed = normalize(snippet.current_text) != normalize(text)
    trust = user.trust if user.trust is not None else 50
    points = 0
    badges: list[str] = []
    db.add(
        EditHistory(
            snippet_id=snippet.id,
            volunteer_id=user.id,
            previous_text=snippet.current_text,
            new_text=text,
            review_state="live",
        )
    )
    points = 25 if changed else 10
    snippet.current_text = text
    snippet.status = "verified"
    snippet.verified_at = utcnow()
    snippet.claimed_by_id = None
    snippet.claimed_at = None
    user.points = (user.points or 0) + points
    if changed:
        user.trust = min(100, trust + 2)
    recompute_document(snippet.document)
    db.flush()
    corrections, confirms = _counts(db, user)
    badges = award_new(db, user, corrections, confirms)
    db.commit()
    return points, badges


def pending_edits(db: Session) -> list[EditHistory]:
    return (
        db.query(EditHistory)
        .filter(EditHistory.review_state == "pending")
        .order_by(EditHistory.created_at.asc())
        .all()
    )


def moderate(db: Session, reviewer: User, edit_id: int, decision: str) -> None:
    if reviewer.role != "volunteer":
        raise AppError("forbidden_reader", 403)
    if (reviewer.trust or 0) < TRUST_MODERATE:
        raise AppError("trust_low", 403)
    edit = db.get(EditHistory, edit_id)
    if edit is None or edit.review_state != "pending":
        raise AppError("not_found", 404)
    if edit.volunteer_id == reviewer.id:
        raise AppError("own_edit", 403)
    editor = db.get(User, edit.volunteer_id)
    snippet = edit.snippet
    if editor is None or snippet is None:
        raise AppError("not_found", 404)
    if decision == "approve" and abuse_introduced(edit.previous_text, edit.new_text):
        edit.review_state = "rejected"
        suspend(editor)
        snippet.status = "flagged"
        snippet.claimed_by_id = None
        snippet.claimed_at = None
        recompute_document(snippet.document)
        db.commit()
        raise AppError("content_blocked", 400)
    if decision == "approve":
        snippet.current_text = edit.new_text
        snippet.status = "verified"
        snippet.verified_at = utcnow()
        snippet.claimed_by_id = None
        snippet.claimed_at = None
        edit.review_state = "live"
        editor.points = (editor.points or 0) + 25
        editor.trust = min(100, (editor.trust or 50) + 4)
        recompute_document(snippet.document)
        db.flush()
        corrections, confirms = _counts(db, editor)
        award_new(db, editor, corrections, confirms)
    elif decision == "reject":
        edit.review_state = "rejected"
        editor.trust = max(0, (editor.trust or 50) - 12)
        snippet.status = "flagged"
        snippet.claimed_by_id = None
        snippet.claimed_at = None
        recompute_document(snippet.document)
    else:
        raise AppError("not_found", 404)
    db.commit()


def stats_for(db: Session, user: User) -> dict:
    corrections, confirms = _counts(db, user)
    earned = {badge.badge_key for badge in user.badges}
    rank = (
        db.query(User)
        .filter(User.role == "volunteer", User.points > (user.points or 0))
        .count()
        + 1
    )
    upcoming = next_correction_badge(corrections, earned)
    return {
        "points": user.points or 0,
        "trust": user.trust if user.trust is not None else 50,
        "corrections": corrections,
        "confirms": confirms,
        "rank": rank,
        "badges": progress(corrections, confirms, earned),
        "next_badge": upcoming,
    }


def _period_start(period: str):
    now = utcnow()
    if period == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "year":
        return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def leaderboard(db: Session, user: User, period: str = "month", limit: int = 8) -> list[dict]:
    """Rank volunteers by points earned in the current day, month, or year."""
    if period not in {"day", "month", "year"}:
        period = "month"
    start = _period_start(period)
    edits = (
        db.query(EditHistory)
        .filter(EditHistory.review_state == "live", EditHistory.created_at >= start)
        .all()
    )
    scores: dict[int, int] = {}
    for edit in edits:
        same = normalize(edit.previous_text) == normalize(edit.new_text)
        scores[edit.volunteer_id] = scores.get(edit.volunteer_id, 0) + (10 if same else 25)
    volunteers = db.query(User).filter(User.role == "volunteer").all()
    ranked = sorted(volunteers, key=lambda row: (-scores.get(row.id, 0), row.display_name))
    scored = [row for row in ranked if scores.get(row.id, 0) > 0]
    ranks = {row.id: index for index, row in enumerate(scored, start=1)}
    visible = scored[:limit]
    if user.id not in {row.id for row in visible}:
        visible.append(user)
    return [
        {
            "name": row.display_name,
            "points": scores.get(row.id, 0),
            "you": row.id == user.id,
            "rank": ranks.get(row.id, len(scored) + 1),
        }
        for row in visible
    ]
