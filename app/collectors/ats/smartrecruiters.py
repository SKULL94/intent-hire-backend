from __future__ import annotations

import asyncio
import logging

import httpx

from app.collectors.ats.base import ATSAdapter
from app.utils.role_filter import is_technical_role
from app.utils.text_cleaner import html_to_text

log = logging.getLogger(__name__)

# Hydrating a posting costs one request each, so bound it. This only needs to
# cover what the collector will actually use (MAX_JOBS_FOR_STACK_EXTRACTION).
MAX_HYDRATED_POSTINGS = 20
HYDRATION_CONCURRENCY = 5


class SmartRecruitersAdapter(ATSAdapter):
    BASE = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    DETAIL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings/{posting_id}"

    def ats_name(self) -> str:
        return "smartrecruiters"

    async def fetch_jobs(self, client: httpx.AsyncClient, ats_slug: str) -> list[dict]:
        resp = await client.get(self.BASE.format(slug=ats_slug))
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        jobs = [self._normalize(job) for job in data.get("content", [])]
        await self._hydrate_descriptions(client, ats_slug, jobs)
        return jobs

    async def _hydrate_descriptions(
        self, client: httpx.AsyncClient, ats_slug: str, jobs: list[dict]
    ) -> None:
        """Fill in `description` for technical roles, in place.

        Unlike every other ATS we support, SmartRecruiters' list endpoint returns
        postings *without* their `jobAd` body — descriptions only exist on the
        per-posting detail endpoint. Without this step the adapter yields titles
        with empty descriptions, so SmartRecruiters companies produce intent
        signals but can never produce a stack fingerprint.

        Only technical roles are hydrated: a sales posting's description is not
        something we would extract a stack from anyway (see utils.role_filter).
        """
        targets = [j for j in jobs if is_technical_role(j.get("title"))][:MAX_HYDRATED_POSTINGS]
        if not targets:
            return

        semaphore = asyncio.Semaphore(HYDRATION_CONCURRENCY)

        async def hydrate(job: dict) -> None:
            async with semaphore:
                url = self.DETAIL.format(slug=ats_slug, posting_id=job["external_id"])
                try:
                    detail = await client.get(url)
                    detail.raise_for_status()
                except httpx.HTTPError as exc:
                    log.warning("SmartRecruiters detail fetch failed for %s: %s", url, exc)
                    return
                try:
                    job["description"] = self._description_from(detail.json())
                except ValueError:
                    log.warning("SmartRecruiters detail returned non-JSON for %s", url)

        await asyncio.gather(*(hydrate(j) for j in targets))

    @staticmethod
    def _description_from(payload: dict) -> str:
        sections = ((payload.get("jobAd") or {}).get("sections") or {})
        description_html = "\n\n".join(
            (sections.get(k) or {}).get("text", "")
            for k in ("companyDescription", "jobDescription", "qualifications", "additionalInformation")
            if sections.get(k)
        )
        return html_to_text(description_html)

    @classmethod
    def _normalize(cls, job: dict) -> dict:
        location = job.get("location") or {}
        location_str = ", ".join(
            filter(None, [location.get("city"), location.get("country")])
        )
        department = (job.get("department") or {}).get("label")
        return {
            "title": job.get("name", "").strip(),
            "location": location_str or None,
            "department": department,
            # The list endpoint has no jobAd; _hydrate_descriptions fills this in.
            "description": cls._description_from(job),
            "posted_at": job.get("releasedDate") or job.get("createdOn"),
            "url": job.get("ref") or job.get("applyUrl"),
            "external_id": str(job.get("id")),
        }
