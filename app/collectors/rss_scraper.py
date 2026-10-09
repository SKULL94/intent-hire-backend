"""Indian funding & news feeds, as a company *discovery* source.

This collector used to ask "does this article mention one of the companies we
already track?" and drop everything else. Measured against a live fetch, that
kept 1 of 44 entries — and the one it kept was a retail-sales piece, not a
hiring signal. Meanwhile the feeds carried real funding news (NeoGrowth, Rs 85
Cr; DailyObjects, Rs 332 Cr Series C) that was discarded for the exact reason
it was valuable: the company was new to us.

So the funnel is inverted. Every entry goes to Claude, which identifies *which*
company the article is about; that company is then resolved against the tracked
set or created. A funding announcement is a discovery event, not a lookup.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import feedparser
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector
from app.collectors.company_resolver import resolve_or_create
from app.models.intent_signal import IntentSignal
from app.processors.llm_classifier import extract_article_event
from app.utils.text_cleaner import normalize_whitespace, truncate

log = logging.getLogger(__name__)

FEEDS: dict[str, str] = {
    # Indian startup/funding press — the India-specific counterweight to the
    # ATS collectors, which are structurally US-biased because Greenhouse,
    # Lever and Ashby are US products.
    "inc42": "https://inc42.com/feed/",
    "inc42_buzz": "https://inc42.com/buzz/feed/",
    # Entrackr moved to /rss; /feed/ has been 404ing and the old code swallowed
    # the error, silently losing a third of the sources.
    "entrackr": "https://entrackr.com/rss",
    "yourstory": "https://yourstory.com/feed",
    "startupstory": "https://startupstorymedia.com/feed/",
}

# Entries per feed per run. Feeds carry ~20-25; this bounds LLM spend if one
# ever returns a huge archive page.
MAX_ENTRIES_PER_FEED = 40

# Claude calls in flight. Each entry is one Haiku call.
CLASSIFY_CONCURRENCY = 5

# An article is evidence a company exists and did something; it is weaker
# evidence of the tech they build with than a job posting or a dependency file.
ARTICLE_TECH_CONFIDENCE = 0.6

# One funding signal per company per window.
#
# A single raise gets reported by every outlet we read — one run produced four
# NeoGrowth rows and four DailyObjects rows. `funding` is not a snapshot signal,
# so the scoring engine *sums* them: at weight 30, four duplicates reach the
# 100 cap on their own and a single widely-covered raise outranks a company
# with a genuinely strong hiring profile. A company raising twice in a month is
# rare; the same raise reported four times is the norm.
FUNDING_DEDUPE_DAYS = 30


class RSSCollector(BaseCollector):
    def source_name(self) -> str:
        return "rss"

    async def _fetch_entries(self, feed_name: str, url: str) -> list[dict]:
        try:
            await self.rate_limiter.acquire(feed_name)
            resp = await self.client.get(url)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            # Loud on purpose. A dead feed is a silent 33% data loss, and that
            # is exactly how the Entrackr 404 went unnoticed.
            log.error("FEED DOWN %s (%s): %s", feed_name, url, exc)
            return []

        feed = feedparser.parse(resp.text)
        if feed.bozo and not feed.entries:
            log.error("FEED UNPARSEABLE %s (%s): %s", feed_name, url, feed.bozo_exception)
            return []

        entries = feed.entries[:MAX_ENTRIES_PER_FEED]
        log.info("%s: %d entries", feed_name, len(entries))
        return entries

    @staticmethod
    def _entry_text(entry: dict) -> str:
        title = entry.get("title", "")
        summary = normalize_whitespace(entry.get("summary", "")) or entry.get("description", "")
        return f"{title}\n{summary}"

    async def collect_all(self, db: Session) -> dict[str, Any]:
        semaphore = asyncio.Semaphore(CLASSIFY_CONCURRENCY)

        async def classify(text: str):
            async with semaphore:
                return await extract_article_event(truncate(text, 4000))

        intent_rows: list[dict] = []
        stack_rows: list[dict] = []
        now = datetime.now(timezone.utc)

        # Seeded from the database so the guard also holds across runs, not
        # just across feeds within one run.
        funded_recently: set[UUID] = set(
            db.execute(
                select(IntentSignal.company_id).where(
                    IntentSignal.signal_type == "funding",
                    IntentSignal.detected_at >= now - timedelta(days=FUNDING_DEDUPE_DAYS),
                )
            ).scalars()
        )

        for feed_name, url in FEEDS.items():
            entries = await self._fetch_entries(feed_name, url)
            if not entries:
                continue

            texts = [self._entry_text(e) for e in entries]
            results = await asyncio.gather(
                *(classify(t) for t in texts), return_exceptions=True
            )

            kept = 0
            for entry, text, result in zip(entries, texts, results):
                if isinstance(result, Exception) or not result:
                    continue
                if not result.get("has_hiring_signal"):
                    continue

                event_type = result.get("event_type")
                if event_type not in ("funding", "expansion", "news"):
                    continue

                company_name = (result.get("company") or "").strip()
                if not company_name:
                    continue

                company = await resolve_or_create(
                    db,
                    self.client,
                    company_name,
                    domain=(result.get("domain") or None),
                )
                if company is None:
                    continue

                if not company.location and result.get("location"):
                    company.location = result["location"]

                # 'expansion' is announced hiring, which the scoring engine has
                # no weight for; score it as news. Funding keeps its own type
                # because it carries weight 30 and a slow decay.
                signal_type = "funding" if event_type == "funding" else "news"
                if signal_type == "funding":
                    if company.id in funded_recently:
                        log.debug("Duplicate funding event for %s, skipping", company.name)
                        continue
                    funded_recently.add(company.id)

                link = entry.get("link")

                intent_rows.append(
                    {
                        "company_id": company.id,
                        "signal_type": signal_type,
                        "source": link or f"feed:{feed_name}",
                        "raw_data": {"title": entry.get("title", ""), "summary": text[:1000]},
                        "extracted": result,
                        "confidence": float(result.get("confidence") or 0.5),
                        "detected_at": now,
                    }
                )
                kept += 1

                techs = result.get("technologies_mentioned") or []
                if techs:
                    stack_rows.append(
                        {
                            "company_id": company.id,
                            "source_type": "blog",
                            "source_url": link,
                            "technologies": {t: ARTICLE_TECH_CONFIDENCE for t in techs},
                            "raw_evidence": (result.get("evidence") or text)[:500],
                            "detected_at": now,
                        }
                    )

            log.info("%s: %d/%d entries produced a signal", feed_name, kept, len(entries))

        return {"intent": intent_rows, "stack": stack_rows}

    async def collect(self, company) -> dict[str, Any]:
        # RSS collection is global, not per-company.
        return {"intent": [], "stack": []}
