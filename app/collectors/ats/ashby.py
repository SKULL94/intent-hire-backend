from __future__ import annotations

import httpx

from app.collectors.ats.base import ATSAdapter
from app.utils.text_cleaner import html_to_text


class AshbyAdapter(ATSAdapter):
    BASE = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"

    def ats_name(self) -> str:
        return "ashby"

    async def fetch_jobs(self, client: httpx.AsyncClient, ats_slug: str) -> list[dict]:
        resp = await client.get(self.BASE.format(slug=ats_slug))
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        return [self._normalize(job) for job in data.get("jobs", [])]

    @staticmethod
    def _normalize(job: dict) -> dict:
        return {
            "title": job.get("title", "").strip(),
            "location": job.get("location"),
            "department": job.get("department"),
            "description": html_to_text(job.get("descriptionHtml", "") or job.get("descriptionPlain", "")),
            "posted_at": job.get("publishedAt") or job.get("updatedAt"),
            "url": job.get("jobUrl") or job.get("applyUrl"),
            "external_id": str(job.get("id")),
        }
