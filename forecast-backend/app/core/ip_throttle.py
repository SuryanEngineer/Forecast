"""
Tiny in-memory sliding-window limiter, keyed by client IP (or anything else).

Used as a backstop on "send me a code" so one machine can't make the site email hundreds of people (and burn the Gmail
relay's ~100/day quota). The per-account limits in auth_code_service are the main protection; this one covers requests
spread across many accounts. State lives in this process only -- fine for a single Render instance, and a restart just
forgets the counts.
"""
from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, max_keys: int = 5000) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._max_keys = max_keys

    def allow(self, key: str, max_hits: int, window_seconds: float, now: float | None = None) -> bool:
        """True (and the hit is recorded) if `key` has made fewer than `max_hits` allowed calls in the last
        `window_seconds`. Refused calls are not recorded, so waiting out the window always works."""
        if max_hits <= 0:
            return True  # 0 / negative = limiter switched off
        t = time.monotonic() if now is None else now
        with self._lock:
            dq = self._hits.setdefault(key, deque())
            while dq and t - dq[0] >= window_seconds:
                dq.popleft()
            if len(dq) >= max_hits:
                return False
            dq.append(t)
            if len(self._hits) > self._max_keys:  # bound memory: drop keys whose hits have all expired
                for k in [k for k, d in self._hits.items() if not d or t - d[-1] >= window_seconds]:
                    del self._hits[k]
            return True

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


# "Send me a password-reset code" requests, per client IP.
password_reset_limiter = SlidingWindowLimiter()
