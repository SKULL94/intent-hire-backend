"""RemoteOK — remote-first job board, JSON API, no auth.

Flutter/Dart are pre-filtered at the source via `?tag=flutter` and `?tag=dart`,
so every row returned is already in-ICP for technology. Every posting is
remote by definition, but a sizeable fraction is geo-restricted in the body
("USA only", "US timezone") — those get dropped before we create a company
row for them, since an Indian candidate cannot fill them.
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

BASE = "https://remoteok.com/api"
TAGS = ("flutter", "dart")

# No published quota; they ask for a UA (set in BaseCollector) and 429 cheaply.
REQUESTS_PER_SECOND = 0.5

_HTML_TAG = re.compile(r"<[^>]+>")


def _strip_html(s: str) -> str:
    return normalize_whitespace(_HTML_TAG.sub(" ", s or ""))


class RemoteOKCollector(BaseCollector):
    def __init__(self) -> None:
        super().__init__(requests_per_second=REQUESTS_PER_SECOND)

    def source_name(self) -> str:
        return "remoteok"

    async def _fetch(self, tag: str) -> list[dict]:
        await self.rate_limiter.acquire("remoteok")
        try:
            resp = await self.client.get(BASE, params={"tag": tag})
            resp.raise_for_status()
        except httpx.HTTPError:
            log.exception("RemoteOK request failed for tag=%s", tag)
            return []
        try:
            data = resp.json()
        except ValueError:
            log.warning("RemoteOK returned non-JSON for tag=%s", tag)
            return []
        # First element of the response array is a legal/metadata object, not a
        # job. Only strip it when it is actually there.
        if isinstance(data, list) and data and isinstance(data[0], dict) and "legal" in data[0]:
            data = data[1:]
        return data if isinstance(data, list) else []

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
                external_id = str(j.get("id") or j.get("slug") or "")
                if not external_id or external_id in seen:
                    continue
                seen.add(external_id)

                title = (j.get("position") or "").strip()
                if not title:
                    continue

                description = _strip_html(j.get("description") or "")

                # Belt-and-braces: the `?tag=flutter` filter still returns some
                # roles where Flutter is only a nice-to-have. Require either
                # word to appear in title or body.
                techs = detect_technologies(title, description)
                if "flutter" not in techs and "dart" not in techs:
                    continue

                location_raw = (j.get("location") or "").strip()
                if not is_india_allowed(f"{title}\n{location_raw}\n{description[:1500]}"):
                    continue

                company_name = (j.get("company") or "").strip()
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
                date_str = j.get("date")
                if date_str:
                    try:
                        posted_at = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
                    except ValueError:
                        pass

                job_rows.append(
                    {
                        "company_id": company.id,
                        "source": "remoteok",
                        "external_id": f"remoteok:{external_id}",
                        "title": title,
                        "url": j.get("url") or j.get("apply_url"),
                        "department": None,
                        "description": description[:4000] or None,
                        "location_raw": location_raw or None,
                        "location_normalized": location_normalized,
                        "is_remote": True,
                        "technologies": techs,
                        "min_years_experience": parse_min_years(description),
                        "salary_min": j.get("salary_min"),
                        "salary_max": j.get("salary_max"),
                        "contract_time": None,
                        "posted_at": posted_at,
                        "last_seen_at": now,
                    }
                )
                kept += 1
            log.info("remoteok tag=%s -> %d/%d kept", tag, kept, len(jobs))

        return {"intent": [], "stack": [], "jobs": job_rows}

    async def collect(self, company) -> dict[str, Any]:
        return {"intent": [], "stack": [], "jobs": []}
