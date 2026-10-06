from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.config import settings
from app.utils.rate_limiter import RateLimiter


class BaseCollector(ABC):
    """Shared httpx client + rate limiter + lifecycle for all collectors."""

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "HireSignal/1.0 (hiring-intent-research)"},
            follow_redirects=True,
        )
        rate = 1.0 / settings.scrape_rate_limit if settings.scrape_rate_limit > 0 else 0.5
        self.rate_limiter = RateLimiter(requests_per_second=rate)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.aclose()

    @abstractmethod
    def source_name(self) -> str:
        ...

    @abstractmethod
    async def collect(self, company) -> dict[str, Any]:
        """Return `{'intent': [...], 'stack': [...]}` dicts of rows to persist."""
