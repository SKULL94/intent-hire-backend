"""Self-hosted Wappalyzer web-stack detection.

Note: python-Wappalyzer is a blocking library — we run it in a thread via
asyncio.to_thread so the event loop stays responsive.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import anyio

from app.collectors.base import BaseCollector
from app.models.company import Company
from app.utils.text_cleaner import normalize_tech_name

log = logging.getLogger(__name__)


def _analyze_sync(url: str) -> dict[str, Any]:
    # Import inside to avoid network calls at module import time.
    from Wappalyzer import Wappalyzer, WebPage

    wappalyzer = Wappalyzer.latest()
    page = WebPage.new_from_url(url)
    return wappalyzer.analyze_with_versions_and_categories(page)


class WappalyzerCollector(BaseCollector):
    def source_name(self) -> str:
        return "wappalyzer"

    async def collect(self, company: Company) -> dict[str, Any]:
        if not company.domain:
            return {"intent": [], "stack": []}

        url = f"https://{company.domain}"
        await self.rate_limiter.acquire(company.domain)
        try:
            detections = await anyio.to_thread.run_sync(_analyze_sync, url)
        except Exception:  # noqa: BLE001
            log.exception("Wappalyzer failed for %s", url)
            return {"intent": [], "stack": []}

        techs: dict[str, float] = {}
        for name in detections or {}:
            techs[normalize_tech_name(name)] = 0.7  # web-stack confidence (per spec)

        if not techs:
            return {"intent": [], "stack": []}

        return {
            "intent": [],
            "stack": [
                {
                    "company_id": company.id,
                    "source_type": "wappalyzer",
                    "source_url": url,
                    "technologies": techs,
                    "raw_evidence": None,
                    "detected_at": datetime.now(timezone.utc),
                }
            ],
        }
