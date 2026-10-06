from __future__ import annotations

import httpx

from app.collectors.ats.base import ATSAdapter
from app.utils.text_cleaner import html_to_text, normalize_whitespace


class LeverAdapter(ATSAdapter):
    BASE = "https://api.lever.co/v0/postings/{slug}?mode=json"

    def ats_name(self) -> str:
        return "lever"

    async def fetch_jobs(self, client: httpx.AsyncClient, ats_slug: str) -> list[dict]:
        resp = await client.get(self.BASE.format(slug=ats_slug))
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return [self._normalize(job) for job in resp.json() or []]

    @staticmethod
    def _normalize(job: dict) -> dict:
        categories = job.get("categories") or {}
        description_html = job.get("descriptionPlain") or job.get("description") or ""
        description = (
            normalize_whitespace(description_html)
            if job.get("descriptionPlain")
            else html_to_text(description_html)
        )
        # Lever has a createdAt in ms since epoch.
        return {
            "title": job.get("text", "").strip(),
            "location": categories.get("location"),
            "department": categories.get("team") or categories.get("department"),
            "description": description,
            "posted_at": job.get("createdAt"),
            "url": job.get("hostedUrl") or job.get("applyUrl"),
            "external_id": str(job.get("id")),
        }
