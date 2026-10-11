"""Arbeitnow — EU-leaning job board, JSON API, no auth.

Flutter yield is small (often < 10 live postings) but the API is free and the
collector is cheap. The feed has no tag filter, so we page through and keep
only rows where the title or body mentions Flutter/Dart. Paging stops when the
API reports no further page.
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
from app.utils.job_parser import detect_technologies, normalize_location, parse_min_years
from app.utils.text_cleaner import normalize_whitespace

log = logging.getLogger(__name__)

BASE = "https://www.arbeitnow.com/api/job-board-api"
MAX_PAGES = 10
REQUESTS_PER_SECOND = 1.0

_HTML_TAG = re.compile(r"<[^>]+>")


def _strip_html(s: str) -> str:
    return normalize_whitespace(_HTML_TAG.sub(" ", s or ""))


class ArbeitnowCollector(BaseCollector):
    def __init__(self) -> None:
        super().__init__(requests_per_second=REQUESTS_PER_SECOND)

    def source_name(self) -> str:
        return "arbeitnow"

    async def _fetch_page(self, page: int) -> tuple[list[dict], bool]:
        await self.rate_limiter.acquire("arbeitnow")
        try:
            resp = await self.client.get(BASE, params={"page": page})
            resp.raise_for_status()
        except httpx.HTTPError:
            log.exception("Arbeitnow request failed for page=%d", page)
            return [], False
        try:
            payload = resp.json()
        except ValueError:
            log.warning("Arbeitnow returned non-JSON for page=%d", page)
            return [], False
        data = payload.get("data") or []
        has_next = bool((payload.get("links") or {}).get("next"))
        return data, has_next

    async def collect_all(self, db: Session) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        job_rows: list[dict] = []
        seen: set[str] = set()
        total_scanned = 0

        for page in range(1, MAX_PAGES + 1):
            jobs, has_next = await self._fetch_page(page)
            if not jobs:
                break
            total_scanned += len(jobs)

            for j in jobs:
                if not isinstance(j, dict):
                    continue
                slug = (j.get("slug") or "").strip()
                if not slug or slug in seen:
                    continue
                seen.add(slug)

                title = (j.get("title") or "").strip()
                if not title:
                    continue
                description = _strip_html(j.get("description") or "")

                techs = detect_technologies(title, description)
                if "flutter" not in techs and "dart" not in techs:
                    continue

                is_remote_api = bool(j.get("remote"))
                location_raw = (j.get("location") or "").strip()
                if not is_india_allowed(f"{title}\n{location_raw}\n{description[:1500]}"):
                    continue
                # On-site in a country India-candidates can't move to without
                # relocation. We only want remote or (very rarely) India-based
                # Arbeitnow postings.
                if not is_remote_api:
                    location_norm_tmp, _ = normalize_location(location_raw)
                    if location_norm_tmp not in {
                        "delhi_ncr", "bengaluru", "mumbai", "pune", "hyderabad",
                        "chennai", "kolkata", "ahmedabad", "india_other", "remote",
                    }:
                        continue

                company_name = (j.get("company_name") or "").strip()
                if not company_name:
                    continue

                company = await resolve_or_create(
                    db, self.client, company_name, probe_ats=False
                )
                if company is None:
                    continue

                location_normalized, _ = normalize_location(location_raw)
                if not company.location and location_raw:
                    company.location = location_raw

                posted_at: datetime | None = None
                ts = j.get("created_at")
                if ts:
                    try:
                        posted_at = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                    except (ValueError, TypeError):
                        pass

                job_types = j.get("job_types") or []
                contract_time = job_types[0] if job_types else None

                job_rows.append(
                    {
                        "company_id": company.id,
                        "source": "arbeitnow",
                        "external_id": f"arbeitnow:{slug}",
                        "title": title,
                        "url": j.get("url"),
                        "department": None,
                        "description": description[:4000] or None,
                        "location_raw": location_raw or None,
                        "location_normalized": location_normalized,
                        "is_remote": is_remote_api or None,
                        "technologies": techs,
                        "min_years_experience": parse_min_years(description),
                        "salary_min": None,
                        "salary_max": None,
                        "contract_time": contract_time,
                        "posted_at": posted_at,
                        "last_seen_at": now,
                    }
                )

            log.info(
                "arbeitnow page=%d scanned=%d kept-total=%d",
                page,
                total_scanned,
                len(job_rows),
            )
            if not has_next:
                break

        return {"intent": [], "stack": [], "jobs": job_rows}

    async def collect(self, company) -> dict[str, Any]:
        return {"intent": [], "stack": [], "jobs": []}
