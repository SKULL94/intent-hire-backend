"""Himalayas — curated remote job board, free JSON API, no auth.

Queries `?q=flutter` and `?q=dart` against the public jobs endpoint.
Every result is a remote posting by definition, but we still run
`is_india_allowed()` on the description to drop any with timezone fences.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector
from app.collectors.company_resolver import resolve_or_create
from app.utils.geo_restriction import is_india_allowed
from app.utils.job_parser import detect_technologies, parse_min_years
from app.utils.text_cleaner import normalize_whitespace

_HTML_TAG = re.compile(r"<[^>]+>")

log = logging.getLogger(__name__)

BASE = "https://himalayas.app/jobs/api"
QUERIES = ("flutter", "dart")
REQUESTS_PER_SECOND = 0.5


class HimalayasCollector(BaseCollector):
    def __init__(self) -> None:
        super().__init__(requests_per_second=REQUESTS_PER_SECOND)

    def source_name(self) -> str:
        return "himalayas"

    async def _fetch(self, query: str) -> list[dict]:
        await self.rate_limiter.acquire("himalayas")
        try:
            resp = await self.client.get(BASE, params={"q": query, "limit": 100})
            resp.raise_for_status()
        except httpx.HTTPError:
            log.exception("Himalayas request failed for q=%s", query)
            return []
        try:
            return resp.json().get("jobs") or []
        except ValueError:
            log.warning("Himalayas returned non-JSON for q=%s", query)
            return []

    async def collect_all(self, db: Session) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        job_rows: list[dict] = []
        seen: set[str] = set()

        for query in QUERIES:
            jobs = await self._fetch(query)
            kept = 0
            for j in jobs:
                if not isinstance(j, dict):
                    continue
                job_id = str(j.get("id") or j.get("slug") or "")
                if not job_id or job_id in seen:
                    continue
                seen.add(job_id)

                title = (j.get("title") or "").strip()
                if not title:
                    continue

                description = normalize_whitespace(
                    _HTML_TAG.sub(" ", j.get("description") or "")
                )
                techs = detect_technologies(title, description)
                if "flutter" not in techs and "dart" not in techs:
                    continue

                if not is_india_allowed(f"{title}\n{description[:1500]}"):
                    continue

                company_data = j.get("company") or {}
                company_name = (
                    company_data.get("name") if isinstance(company_data, dict)
                    else str(company_data)
                ).strip()
                if not company_name:
                    continue

                company_domain = (
                    company_data.get("website") if isinstance(company_data, dict) else None
                )
                company = await resolve_or_create(
                    db, self.client, company_name,
                    domain=company_domain,
                    probe_ats=False,
                )
                if company is None:
                    continue

                posted_at: datetime | None = None
                raw_date = j.get("publishedAt") or j.get("createdAt")
                if raw_date:
                    try:
                        posted_at = datetime.fromisoformat(
                            str(raw_date).replace("Z", "+00:00")
                        )
                    except ValueError:
                        pass

                job_rows.append(
                    {
                        "company_id": company.id,
                        "source": "himalayas",
                        "external_id": f"himalayas:{job_id}",
                        "title": title,
                        "url": j.get("url") or j.get("applyUrl"),
                        "department": j.get("department"),
                        "description": description[:4000] or None,
                        "location_raw": j.get("location") or "Remote",
                        "location_normalized": None,
                        "is_remote": True,
                        "technologies": techs,
                        "min_years_experience": parse_min_years(description),
                        "salary_min": None,
                        "salary_max": None,
                        "contract_time": None,
                        "posted_at": posted_at,
                        "last_seen_at": now,
                    }
                )
                kept += 1
            log.info("himalayas q=%s -> %d/%d kept", query, kept, len(jobs))

        return {"intent": [], "stack": [], "jobs": job_rows}

    async def collect(self, company: Any) -> dict[str, Any]:
        return {"intent": [], "stack": [], "jobs": []}
