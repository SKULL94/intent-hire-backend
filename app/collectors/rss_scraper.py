"""Indian funding & news feeds + per-company engineering blogs.

Match feed entries against known companies by name/domain, classify via Claude,
and persist as `funding` / `news` intent_signals plus `blog` stack_signals when
the LLM mentions technologies.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

import feedparser
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector
from app.models.company import Company
from app.processors.llm_classifier import classify_signal
from app.utils.text_cleaner import normalize_whitespace, truncate

log = logging.getLogger(__name__)

FEEDS: dict[str, str] = {
    "inc42": "https://inc42.com/feed/",
    "entrackr": "https://entrackr.com/feed/",
    "yourstory": "https://yourstory.com/feed",
    # Engineering blogs — add as discovered.
    # "razorpay_eng": "https://razorpay.com/blog/engineering/feed/",
}

_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def _match_companies(text: str, companies: list[Company]) -> list[Company]:
    tokens = {t.lower() for t in _WORD_RE.findall(text)}
    text_lower = text.lower()
    matches: list[Company] = []
    for c in companies:
        name_tokens = {t.lower() for t in _WORD_RE.findall(c.name or "")}
        # Full-word match on the company name (avoid "Pine" matching "pineapple").
        if name_tokens and name_tokens.issubset(tokens):
            matches.append(c)
            continue
        if c.domain and c.domain.lower() in text_lower:
            matches.append(c)
    return matches


class RSSCollector(BaseCollector):
    def source_name(self) -> str:
        return "rss"

    async def collect_all(self, db: Session) -> dict[str, Any]:
        companies = list(db.execute(select(Company).where(Company.is_active.is_(True))).scalars())
        intent_rows: list[dict] = []
        stack_rows: list[dict] = []

        for feed_name, url in FEEDS.items():
            try:
                await self.rate_limiter.acquire(feed_name)
                resp = await self.client.get(url)
                resp.raise_for_status()
                feed = feedparser.parse(resp.text)
            except Exception:  # noqa: BLE001
                log.exception("RSS fetch failed: %s", feed_name)
                continue

            for entry in feed.entries:
                title = entry.get("title", "")
                summary = normalize_whitespace(entry.get("summary", "")) or entry.get("description", "")
                combined = f"{title}\n{summary}"
                matched = _match_companies(combined, companies)
                if not matched:
                    continue

                results = await asyncio.gather(
                    *(
                        classify_signal(c.name, "news_or_funding", truncate(combined, 4000))
                        for c in matched
                    ),
                    return_exceptions=True,
                )

                now = datetime.now(timezone.utc)
                for company, result in zip(matched, results):
                    if isinstance(result, Exception) or not result:
                        continue
                    if not result.get("has_hiring_signal"):
                        continue
                    sig_type = result.get("signal_type")
                    if sig_type not in ("funding", "news"):
                        continue
                    confidence = float(result.get("confidence") or 0.5)
                    link = entry.get("link")
                    intent_rows.append(
                        {
                            "company_id": company.id,
                            "signal_type": sig_type,
                            "source": link or f"feed:{feed_name}",
                            "raw_data": {"title": title, "summary": summary[:1000]},
                            "extracted": result,
                            "confidence": confidence,
                            "detected_at": now,
                        }
                    )
                    techs = result.get("technologies_mentioned") or []
                    if techs:
                        stack_rows.append(
                            {
                                "company_id": company.id,
                                "source_type": "blog" if "blog" in feed_name else "hn_whos_hiring",
                                "source_url": link,
                                "technologies": {t: 0.6 for t in techs},
                                "raw_evidence": summary[:500],
                                "detected_at": now,
                            }
                        )

        return {"intent": intent_rows, "stack": stack_rows}

    async def collect(self, company: Company) -> dict[str, Any]:
        # Not used — RSS collection is global, not per-company.
        return {"intent": [], "stack": []}
