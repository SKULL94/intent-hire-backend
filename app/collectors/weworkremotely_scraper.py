"""We Work Remotely — large curated remote board, RSS feed, no auth.

WWR's programming category RSS returns all dev roles. We filter for
Flutter/Dart mentions in title + description. Every posting is remote.
`is_india_allowed()` drops timezone-fenced US-only roles.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import feedparser
from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector
from app.collectors.company_resolver import resolve_or_create
from app.utils.geo_restriction import is_india_allowed
from app.utils.job_parser import detect_technologies, parse_min_years
from app.utils.text_cleaner import normalize_whitespace

log = logging.getLogger(__name__)

FEEDS = {
    "wwr_programming": "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "wwr_design": "https://weworkremotely.com/categories/remote-design-jobs.rss",
}

_HTML_TAG = re.compile(r"<[^>]+>")
REQUESTS_PER_SECOND = 0.5


def _clean(text: str) -> str:
    return normalize_whitespace(_HTML_TAG.sub(" ", text or ""))


class WeWorkRemotelyCollector(BaseCollector):
    def __init__(self) -> None:
        super().__init__(requests_per_second=REQUESTS_PER_SECOND)

    def source_name(self) -> str:
        return "weworkremotely"

    async def _fetch_feed(self, name: str, url: str) -> list[Any]:
        await self.rate_limiter.acquire(name)
        try:
            resp = await self.client.get(url)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            log.error("WWR feed down %s: %s", name, exc)
            return []
        feed = feedparser.parse(resp.text)
        if feed.bozo and not feed.entries:
            log.error("WWR feed unparseable %s: %s", name, feed.bozo_exception)
            return []
        log.info("wwr %s: %d entries", name, len(feed.entries))
        return feed.entries

    async def collect_all(self, db: Session) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        job_rows: list[dict] = []
        seen: set[str] = set()

        for feed_name, feed_url in FEEDS.items():
            entries = await self._fetch_feed(feed_name, feed_url)
            kept = 0
            for entry in entries:
                link = entry.get("link") or ""
                if not link or link in seen:
                    continue
                seen.add(link)

                title = _clean(entry.get("title") or "")
                # WWR title format: "Company | Job Title" — extract company name
                company_name = ""
                job_title = title
                if " | " in title:
                    parts = title.split(" | ", 1)
                    company_name = parts[0].strip()
                    job_title = parts[1].strip()

                summary = _clean(
                    entry.get("summary")
                    or entry.get("description")
                    or ""
                )

                # Only keep Flutter/Dart roles
                techs = detect_technologies(job_title, summary)
                if "flutter" not in techs and "dart" not in techs:
                    continue

                if not is_india_allowed(f"{job_title}\n{summary[:1500]}"):
                    continue

                if not company_name:
                    continue

                company = await resolve_or_create(
                    db, self.client, company_name, probe_ats=False
                )
                if company is None:
                    continue

                posted_at: datetime | None = None
                published = entry.get("published_parsed")
                if published:
                    try:
                        posted_at = datetime(*published[:6], tzinfo=timezone.utc)
                    except Exception:
                        pass

                job_rows.append(
                    {
                        "company_id": company.id,
                        "source": "weworkremotely",
                        "external_id": f"wwr:{link}",
                        "title": job_title,
                        "url": link,
                        "department": None,
                        "description": summary[:4000] or None,
                        "location_raw": "Remote",
                        "location_normalized": None,
                        "is_remote": True,
                        "technologies": techs,
                        "min_years_experience": parse_min_years(summary),
                        "salary_min": None,
                        "salary_max": None,
                        "contract_time": None,
                        "posted_at": posted_at,
                        "last_seen_at": now,
                    }
                )
                kept += 1
            log.info("wwr %s -> %d kept", feed_name, kept)

        return {"intent": [], "stack": [], "jobs": job_rows}

    async def collect(self, company: Any) -> dict[str, Any]:
        return {"intent": [], "stack": [], "jobs": []}
