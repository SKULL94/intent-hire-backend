from __future__ import annotations

import httpx

from app.collectors.ats.base import ATSAdapter
from app.utils.text_cleaner import html_to_text


class SmartRecruitersAdapter(ATSAdapter):
    BASE = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"

    def ats_name(self) -> str:
        return "smartrecruiters"

    async def fetch_jobs(self, client: httpx.AsyncClient, ats_slug: str) -> list[dict]:
        resp = await client.get(self.BASE.format(slug=ats_slug))
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        return [self._normalize(job) for job in data.get("content", [])]

    @staticmethod
    def _normalize(job: dict) -> dict:
        location = job.get("location") or {}
        location_str = ", ".join(
            filter(None, [location.get("city"), location.get("country")])
        )
        department = (job.get("department") or {}).get("label")
        job_ad = job.get("jobAd") or {}
        sections = (job_ad.get("sections") or {})
        description_html = "\n\n".join(
            (sections.get(k) or {}).get("text", "")
            for k in ("companyDescription", "jobDescription", "qualifications", "additionalInformation")
            if sections.get(k)
        )
        return {
            "title": job.get("name", "").strip(),
            "location": location_str or None,
            "department": department,
            "description": html_to_text(description_html),
            "posted_at": job.get("releasedDate") or job.get("createdOn"),
            "url": job.get("ref") or job.get("applyUrl"),
            "external_id": str(job.get("id")),
        }
