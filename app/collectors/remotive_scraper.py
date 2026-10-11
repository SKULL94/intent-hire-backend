"""Remotive — remote-jobs JSON API, no auth.

Flutter/Dart filtered via the `search` parameter and verified with
`detect_technologies`. The posting's structured `candidate_required_location`
field is the primary geo filter (controlled vocabulary); the loose regex over
the description is the fallback for stray US-only clauses the structured field
missed.
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
from app.utils.geo_restriction import is_india_allowed, remotive_region_allows_india
from app.utils.job_parser import detect_technologies, normalize_location, parse_min_years
from app.utils.text_cleaner import normalize_whitespace

log = logging.getLogger(__name__)

BASE = "https://remotive.com/api/remote-jobs"
QUERIES = ("flutter", "dart")

REQUESTS_PER_SECOND = 1.0

_HTML_TAG = re.compile(r"<[^>]+>")
_NUM = re.compile(r"(\d[\d,]*\.?\d*)\s*(k)?", re.I)


def _strip_html(s: str) -> str:
    return normalize_whitespace(_HTML_TAG.sub(" ", s or ""))


def _parse_salary(raw: str | None) -> tuple[float | None, float | None]:
    """Best-effort (min, max) extraction. Remotive does not normalize currency,
    so these numbers are display-only and not directly comparable across rows.
    """
    if not raw:
        return None, None
    nums: list[float] = []
    for m in _NUM.finditer(raw):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if m.group(2):
            v *= 1000
        if 1_000 <= v <= 1_000_000:
            nums.append(v)
    if not nums:
        return None, None
    if len(nums) == 1:
        return nums[0], None
    return min(nums), max(nums)


class RemotiveCollector(BaseCollector):
    def __init__(self) -> None:
        super().__init__(requests_per_second=REQUESTS_PER_SECOND)

    def source_name(self) -> str:
        return "remotive"

    async def _search(self, query: str) -> list[dict]:
        await self.rate_limiter.acquire("remotive")
        try:
            resp = await self.client.get(
                BASE, params={"category": "software-dev", "search": query}
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            log.exception("Remotive request failed for q=%s", query)
            return []
        try:
            return resp.json().get("jobs") or []
        except ValueError:
            log.warning("Remotive returned non-JSON for q=%s", query)
            return []

    async def collect_all(self, db: Session) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        job_rows: list[dict] = []
        seen: set[str] = set()

        for query in QUERIES:
            jobs = await self._search(query)
            kept = 0
            for j in jobs:
                if not isinstance(j, dict):
                    continue
                external_id = str(j.get("id") or "")
                if not external_id or external_id in seen:
                    continue
                seen.add(external_id)

                title = (j.get("title") or "").strip()
                if not title:
                    continue

                description = _strip_html(j.get("description") or "")

                techs = detect_technologies(title, description)
                if "flutter" not in techs and "dart" not in techs:
                    continue

                required = (j.get("candidate_required_location") or "").strip()
                if not remotive_region_allows_india(required):
                    continue
                if not is_india_allowed(f"{required}\n{description[:1500]}"):
                    continue

                company_name = (j.get("company_name") or "").strip()
                if not company_name:
                    continue

                company = await resolve_or_create(
                    db, self.client, company_name, probe_ats=False
                )
                if company is None:
                    continue

                location_normalized, _ = normalize_location(required)
                salary_min, salary_max = _parse_salary(j.get("salary"))

                if not company.location and required:
                    company.location = required

                posted_at: datetime | None = None
                date_str = j.get("publication_date")
                if date_str:
                    try:
                        posted_at = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
                    except ValueError:
                        pass

                job_rows.append(
                    {
                        "company_id": company.id,
                        "source": "remotive",
                        "external_id": f"remotive:{external_id}",
                        "title": title,
                        "url": j.get("url"),
                        "department": j.get("category"),
                        "description": description[:4000] or None,
                        "location_raw": required or None,
                        "location_normalized": location_normalized,
                        "is_remote": True,
                        "technologies": techs,
                        "min_years_experience": parse_min_years(description),
                        "salary_min": salary_min,
                        "salary_max": salary_max,
                        "contract_time": j.get("job_type"),
                        "posted_at": posted_at,
                        "last_seen_at": now,
                    }
                )
                kept += 1
            log.info("remotive q=%s -> %d/%d kept", query, kept, len(jobs))

        return {"intent": [], "stack": [], "jobs": job_rows}

    async def collect(self, company) -> dict[str, Any]:
        return {"intent": [], "stack": [], "jobs": []}
