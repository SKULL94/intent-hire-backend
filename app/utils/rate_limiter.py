from __future__ import annotations

import asyncio
import time
from collections import defaultdict


class RateLimiter:
    """Simple per-key token-bucket-style limiter.

    Call `await limiter.acquire(key)` before each outbound request. The limiter
    sleeps enough so successive calls for the same key are at least
    `1 / requests_per_second` seconds apart.
    """

    def __init__(self, requests_per_second: float = 0.5):
        self.interval = 1.0 / requests_per_second if requests_per_second > 0 else 0
        self._last_at: dict[str, float] = defaultdict(float)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def acquire(self, key: str = "default") -> None:
        if self.interval <= 0:
            return
        async with self._locks[key]:
            now = time.monotonic()
            wait = self._last_at[key] + self.interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_at[key] = time.monotonic()
