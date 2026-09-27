"""In-memory upload limits for a single server process."""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_hits: dict[str, list[float]] = {}


def allow(key: str, limit: int, window_seconds: int) -> bool:
    now = time.monotonic()
    with _lock:
        recent = [stamp for stamp in _hits.get(key, []) if now - stamp < window_seconds]
        if len(recent) >= limit:
            _hits[key] = recent
            return False
        recent.append(now)
        _hits[key] = recent
        return True


def reset() -> None:
    with _lock:
        _hits.clear()
