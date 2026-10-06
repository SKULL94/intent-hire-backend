from __future__ import annotations

from abc import ABC, abstractmethod

import httpx


class ATSAdapter(ABC):
    """Normalizes a job board's response into the shape downstream consumers expect."""

    @abstractmethod
    def ats_name(self) -> str: ...

    @abstractmethod
    async def fetch_jobs(self, client: httpx.AsyncClient, ats_slug: str) -> list[dict]:
        """Return normalized jobs: {title, location, department, description, posted_at, url, external_id}."""
