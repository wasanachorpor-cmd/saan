"""Badge ladder for volunteer impact."""

from app.models import BadgeAward, User, utcnow

# (key, metric, threshold). Metric is "corrections" or "confirms".
LADDER: list[tuple[str, str, int]] = [
    ("first_light", "corrections", 1),
    ("steady_hand", "corrections", 5),
    ("lighthouse", "corrections", 15),
    ("constellation", "corrections", 40),
    ("faithful", "confirms", 10),
]


def progress(corrections: int, confirms: int, earned: set[str]) -> list[dict]:
    rows = []
    for key, metric, need in LADDER:
        current = corrections if metric == "corrections" else confirms
        rows.append(
            {
                "key": key,
                "earned": key in earned,
                "current": min(current, need),
                "need": need,
            }
        )
    return rows


def next_correction_badge(corrections: int, earned: set[str]) -> tuple[str, int] | None:
    for key, metric, need in LADDER:
        if metric != "corrections" or key in earned:
            continue
        if corrections < need:
            return key, need - corrections
    return None


def award_new(db, user: User, corrections: int, confirms: int) -> list[str]:
    earned = {badge.badge_key for badge in user.badges}
    fresh: list[str] = []
    for key, metric, need in LADDER:
        count = corrections if metric == "corrections" else confirms
        if count >= need and key not in earned:
            db.add(BadgeAward(user_id=user.id, badge_key=key, awarded_at=utcnow()))
            fresh.append(key)
            earned.add(key)
    return fresh
