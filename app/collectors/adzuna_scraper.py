"""Adzuna job-search API — the project's only source of Indian job postings.

Every other collector reaches a company's own job board, which structurally
limits us to companies using Greenhouse/Lever/Ashby — US products. Measured
across the tracked boards, zero postings mentioned Flutter. The same query
against Adzuna's India index returns ~1,000, with ~80 in Delhi NCR.

Adzuna is an aggregator with a licensed API, not a site we scrape. Naukri and
LinkedIn have no public API and scraping them breaches their terms, so they
are not an option here at any level of preference.

Unlike the ATS collectors this is query-driven, not company-driven: we ask for
a technology and get back postings from companies we have never heard of, each
of which is created on the way in.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector
from app.collectors.company_resolver import resolve_or_create
from app.config import settings
from app.utils.job_parser import detect_technologies, normalize_location, parse_min_years
from app.utils.text_cleaner import normalize_whitespace

log = logging.getLogger(__name__)

BASE = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"

# Adzuna caps results_per_page at 50.
RESULTS_PER_PAGE = 50
MAX_PAGES = 5

# The free tier allows 250 calls/day; one call is one page of one query.
REQUESTS_PER_SECOND = 1.0

# Adzuna's index keeps listings long after they close — a spot check returned a
# posting created in 2021. Without this bound most of what we store would be
# dead links, and `intent` would be measuring history.
MAX_DAYS_OLD = 45


class AdzunaCollector(BaseCollector):
    def __init__(self) -> None:
        super().__init__(requests_per_second=REQUESTS_PER_SECOND)

    def source_name(self) -> str:
        return "adzuna"

    async def _search(
        self, country: str, what: str, page: int, where: str | None = None
    ) -> list[dict]:
        params: dict[str, Any] = {
            "app_id": settings.adzuna_app_id,
            "app_key": settings.adzuna_app_key,
            "results_per_page": RESULTS_PER_PAGE,
            "what": what,
            "max_days_old": MAX_DAYS_OLD,
            "content-type": "application/json",
        }
        if where:
            params["where"] = where

        await self.rate_limiter.acquire("adzuna")
        try:
            resp = await self.client.get(
                BASE.format(country=country, page=page), params=params
            )
        except httpx.HTTPError:
            log.exception("Adzuna request failed (%s/%s p%d)", country, what, page)
            return []

        if resp.status_code == 401:
            # Adzuna 401s when either half of the credential pair is missing or
            # wrong, so say which rather than leaving a bare 401 in the log.
            log.error(
                "Adzuna rejected the credentials (app_id %s, app_key %s). "
                "Both come from the same developer.adzuna.com page.",
                "set" if settings.adzuna_app_id else "MISSING",
                "set" if settings.adzuna_app_key else "MISSING",
            )
            return []
        if resp.status_code != 200:
            log.warning("Adzuna HTTP %s for %s/%s p%d", resp.status_code, country, what, page)
            return []

        try:
            return resp.json().get("results") or []
        except ValueError:
            log.warning("Adzuna returned non-JSON for %s/%s p%d", country, what, page)
            return []

    @staticmethod
    def _parse_posted_at(created: str | None) -> datetime | None:
        if not created:
            return None
        try:
            return datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            return None

    async def collect_all(
        self,
        db: Session,
        *,
        queries: list[str],
        country: str = "in",
        locations: list[str | None] | None = None,
    ) -> dict[str, Any]:
        if not settings.adzuna_configured:
            log.error("ADZUNA_APP_ID / ADZUNA_APP_KEY not set - skipping Adzuna run")
            return {"intent": [], "stack": [], "jobs": []}

        # `None` means "no location filter", i.e. the whole country.
        locations = locations or [None]
        now = datetime.now(timezone.utc)
        job_rows: list[dict] = []
        seen_ids: set[str] = set()

        for what in queries:
            for where in locations:
                for page in range(1, MAX_PAGES + 1):
                    results = await self._search(country, what, page, where)
                    if not results:
                        break

                    for r in results:
                        external_id = str(r.get("id") or "")
                        if not external_id or external_id in seen_ids:
                            continue
                        seen_ids.add(external_id)

                        title = (r.get("title") or "").strip()
                        if not title:
                            continue

                        company_name = ((r.get("company") or {}).get("display_name") or "").strip()
                        if not company_name:
                            # Many aggregator rows are posted by recruiters who
                            # hide the client. Without a company there is
                            # nothing to attribute hiring intent to.
                            continue

                        company = await resolve_or_create(
                            db, self.client, company_name, probe_ats=False
                        )
                        if company is None:
                            continue

                        description = normalize_whitespace(r.get("description") or "")
                        location_raw = (r.get("location") or {}).get("display_name")

                        # The city comes from the location field ONLY. Feeding
                        # the description in tagged a Kochi role as delhi_ncr
                        # because its body happened to mention Delhi, which
                        # silently corrupts the filter this collector exists
                        # for. Remote is different: it is routinely stated in
                        # the title or body rather than the location field.
                        location_normalized, remote_from_location = normalize_location(
                            location_raw
                        )
                        _, remote_from_text = normalize_location(
                            f"{title} {description[:400]}"
                        )
                        is_remote = remote_from_location or remote_from_text

                        if not company.location and location_raw:
                            company.location = location_raw

                        job_rows.append(
                            {
                                "company_id": company.id,
                                "source": "adzuna",
                                "external_id": f"adzuna:{external_id}",
                                "title": title,
                                "url": r.get("redirect_url"),
                                "department": (r.get("category") or {}).get("label"),
                                "description": description[:4000] or None,
                                "location_raw": location_raw,
                                "location_normalized": location_normalized,
                                "is_remote": is_remote,
                                # `{}` not None — see the note in ats_collector.
                                "technologies": detect_technologies(title, description),
                                "min_years_experience": parse_min_years(description),
                                "salary_min": r.get("salary_min"),
                                "salary_max": r.get("salary_max"),
                                "contract_time": r.get("contract_time"),
                                "posted_at": self._parse_posted_at(r.get("created")),
                                "last_seen_at": now,
                            }
                        )

                    if len(results) < RESULTS_PER_PAGE:
                        break

                log.info(
                    "adzuna %s/%s %-12s -> %d jobs so far",
                    country,
                    what,
                    where or "(all)",
                    len(job_rows),
                )

        return {"intent": [], "stack": [], "jobs": job_rows}

    async def collect(self, company) -> dict[str, Any]:
        # Adzuna collection is query-driven, not company-driven.
        return {"intent": [], "stack": [], "jobs": []}
