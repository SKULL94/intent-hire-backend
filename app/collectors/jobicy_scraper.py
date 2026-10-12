"""Jobicy — remote job board, free JSON API (no auth), tag-filtered.

`?tag=flutter` returns only Flutter-tagged postings; we do a second pass for
`dart`. Both are remote by definition. `jobGeo` is a structured location field
we check to drop hard US/EU restrictions.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector
from app.collectors.company_resolver import resolve_or_create
from app.utils.geo_restriction import is_india_allowed
from app.utils.job_parser import detect_technologies, parse_min_years
from app.utils.text_cleaner import normalize_whitespace

log = logging.getLogger(__name__)

BASE = "https://jobicy.com/api/v2/remote-jobs"
TAGS = ("flutter", "dart")
REQUESTS_PER_SECOND = 0.5


class JobicyCollector(BaseCollector):
    def __init__(self) -> None:
        super().__init__(requests_per_second=REQUESTS_PER_SECOND)

    def source_name(self) -> str:
        return "jobicy"

    async def _fetch(self, tag: str) -> list[dict]:
        await self.rate_limiter.acquire("jobicy")
        try:
            resp = await self.client.get(BASE, params={"count": 50, "tag": tag})
            resp.raise_for_status()
        except httpx.HTTPError:
            log.exception("Jobicy request failed for tag=%s", tag)
            return []
        try:
            data = resp.json()
            return data.get("jobs") or []
        except ValueError:
            log.warning("Jobicy returned non-JSON for tag=%s", tag)
            return []

    @staticmethod
    def _parse_date(raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            return parsedate_to_datetime(raw)
        except Exception:
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except Exception:
                return None

    async def collect_all(self, db: Session) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        job_rows: list[dict] = []
        seen: set[str] = set()

        for tag in TAGS:
            jobs = await self._fetch(tag)
            kept = 0
            for j in jobs:
                if not isinstance(j, dict):
                    continue
                job_id = str(j.get("id") or "")
                if not job_id or job_id in seen:
                    continue
                seen.add(job_id)

                title = (j.get("jobTitle") or "").strip()
                if not title:
                    continue

                description = normalize_whitespace(j.get("jobDescription") or "")
                techs = detect_technologies(title, description)
                if "flutter" not in techs and "dart" not in techs:
                    continue

                geo = (j.get("jobGeo") or "").strip()
                if not is_india_allowed(f"{geo}\n{description[:1000]}"):
                    continue

                company_name = (j.get("companyName") or "").strip()
                if not company_name:
                    continue

                company = await resolve_or_create(
                    db, self.client, company_name, probe_ats=False
                )
                if company is None:
                    continue

                job_rows.append(
                    {
                        "company_id": company.id,
                        "source": "jobicy",
                        "external_id": f"jobicy:{job_id}",
                        "title": title,
                        "url": j.get("url"),
                        "department": None,
                        "description": description[:4000] or None,
                        "location_raw": geo or "Remote",
                        "location_normalized": None,
                        "is_remote": True,
                        "technologies": techs,
                        "min_years_experience": parse_min_years(description),
                        "salary_min": None,
                        "salary_max": None,
                        "contract_time": j.get("jobType"),
                        "posted_at": self._parse_date(j.get("pubDate")),
                        "last_seen_at": now,
                    }
                )
                kept += 1
            log.info("jobicy tag=%s -> %d/%d kept", tag, kept, len(jobs))

        return {"intent": [], "stack": [], "jobs": job_rows}

    async def collect(self, company: Any) -> dict[str, Any]:
        return {"intent": [], "stack": [], "jobs": []}
