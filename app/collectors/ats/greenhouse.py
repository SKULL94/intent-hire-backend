from __future__ import annotations

import httpx

from app.collectors.ats.base import ATSAdapter
from app.utils.text_cleaner import html_to_text


class GreenhouseAdapter(ATSAdapter):
    BASE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"

    def ats_name(self) -> str:
        return "greenhouse"

    async def fetch_jobs(self, client: httpx.AsyncClient, ats_slug: str) -> list[dict]:
        resp = await client.get(self.BASE.format(slug=ats_slug))
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        return [self._normalize(job) for job in data.get("jobs", [])]

    @staticmethod
    def _normalize(job: dict) -> dict:
        departments = job.get("departments") or []
        return {
            "title": job.get("title", "").strip(),
            "location": (job.get("location") or {}).get("name"),
            "department": departments[0]["name"] if departments else None,
            "description": html_to_text(job.get("content", "")),
            "posted_at": job.get("updated_at") or job.get("first_published"),
            "url": job.get("absolute_url"),
            "external_id": str(job.get("id")),
        }
