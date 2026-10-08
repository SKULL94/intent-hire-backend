from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.config import settings
from app.utils.rate_limiter import RateLimiter


class BaseCollector(ABC):
    """Shared httpx client + rate limiter + lifecycle for all collectors."""

    def __init__(self, requests_per_second: float | None = None) -> None:
        """
        `requests_per_second` overrides the polite scraping default derived from
        SCRAPE_RATE_LIMIT. Collectors that talk to a documented JSON API with a
        published quota (rather than scraping someone's HTML) should pass their
        own rate — the scraping default is far too slow for those.
        """
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "HireSignal/1.0 (hiring-intent-research)"},
            follow_redirects=True,
        )
        if requests_per_second is None:
            requests_per_second = (
                1.0 / settings.scrape_rate_limit if settings.scrape_rate_limit > 0 else 0.5
            )
        self.rate_limiter = RateLimiter(requests_per_second=requests_per_second)

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
