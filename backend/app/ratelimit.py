"""Small thread-safe in-memory token bucket rate limiter."""
from __future__ import annotations

import threading
import time


class TokenBucketLimiter:
    def __init__(self, limit: int = 20, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def consume(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        refill_rate = self.limit / self.window_seconds
        with self._lock:
            tokens, updated = self._buckets.get(key, (float(self.limit), now))
            tokens = min(float(self.limit), tokens + (now - updated) * refill_rate)
            if tokens >= 1:
                self._buckets[key] = (tokens - 1, now)
                return True, 0
            retry_after = max(1, int((1 - tokens) / refill_rate + 0.999))
            self._buckets[key] = (tokens, now)
            return False, retry_after
