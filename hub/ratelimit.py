"""Simple in-memory rate limiter for login and unlock."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from hub import config


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int | None = None) -> None:
        self.limit = limit
        self.window = window_seconds or config.RATE_WINDOW_SECONDS
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.time()
        bucket = self._hits[key]
        cutoff = now - self.window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return False
        bucket.append(now)
        return True
