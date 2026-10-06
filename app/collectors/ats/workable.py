from __future__ import annotations

import httpx

from app.collectors.ats.base import ATSAdapter
from app.utils.text_cleaner import html_to_text


class WorkableAdapter(ATSAdapter):
    BASE = "https://apply.workable.com/api/v3/accounts/{slug}/jobs"

    def ats_name(self) -> str:
        return "workable"

    async def fetch_jobs(self, client: httpx.AsyncClient, ats_slug: str) -> list[dict]:
        resp = await client.get(self.BASE.format(slug=ats_slug))
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        # Workable paginates; results[] holds the postings.
        return [self._normalize(job) for job in data.get("results", [])]

    @staticmethod
    def _normalize(job: dict) -> dict:
        location = job.get("location") or {}
        if isinstance(location, list):
            location = location[0] if location else {}
        location_str = ", ".join(filter(None, [location.get("city"), location.get("country")]))
        description = job.get("description") or job.get("full_description") or ""
        return {
            "title": job.get("title", "").strip(),
            "location": location_str or None,
            "department": job.get("department"),
            "description": html_to_text(description),
            "posted_at": job.get("published_on") or job.get("created_at"),
            "url": job.get("url") or job.get("application_url"),
            "external_id": str(job.get("shortcode") or job.get("id")),
        }
