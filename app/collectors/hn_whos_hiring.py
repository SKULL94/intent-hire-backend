"""Monthly HN 'Who's Hiring' ingest.

Finds the latest 'Ask HN: Who is hiring? (Month YYYY)' story via Algolia,
pulls all top-level comments via the Firebase API, classifies each via Claude,
and resolves company names to existing rows (or skips if unknown).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector
from app.models.company import Company
from app.processors.llm_classifier import classify_hn_comment
from app.utils.text_cleaner import html_to_text

log = logging.getLogger(__name__)

ALGOLIA_SEARCH = "https://hn.algolia.com/api/v1/search"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"

MAX_COMMENTS_PER_RUN = 150


def _match_company_by_name(name: str, companies: list[Company]) -> Company | None:
    norm = name.strip().lower()
    for c in companies:
        if c.name and c.name.strip().lower() == norm:
            return c
    return None


class HNCollector(BaseCollector):
    def source_name(self) -> str:
        return "hn"

    async def _find_latest_thread(self) -> dict | None:
        params = {
            "query": "who is hiring",
            "tags": "story,author_whoishiring",
            "hitsPerPage": 5,
        }
        await self.rate_limiter.acquire("hn_algolia")
        resp = await self.client.get(ALGOLIA_SEARCH, params=params)
        resp.raise_for_status()
        data = resp.json()
        for hit in data.get("hits", []):
            title = (hit.get("title") or "").lower()
            if "who is hiring" in title:
                return hit
        return None

    async def _fetch_item(self, item_id: int) -> dict | None:
        await self.rate_limiter.acquire("hn_fb")
        resp = await self.client.get(HN_ITEM.format(item_id=item_id))
        if resp.status_code != 200:
            return None
        return resp.json()

    async def collect_all(self, db: Session) -> dict[str, Any]:
        story = await self._find_latest_thread()
        if not story:
            log.warning("HN 'Who is hiring' thread not found")
            return {"intent": [], "stack": []}

        story_id = story.get("objectID")
        full_story = await self._fetch_item(int(story_id))
        if not full_story:
            return {"intent": [], "stack": []}

        kids: list[int] = (full_story.get("kids") or [])[:MAX_COMMENTS_PER_RUN]
        comments = await asyncio.gather(*(self._fetch_item(k) for k in kids))
        comments = [c for c in comments if c and c.get("text")]

        companies = list(db.execute(select(Company).where(Company.is_active.is_(True))).scalars())

        classifications = await asyncio.gather(
            *(classify_hn_comment(html_to_text(c["text"])) for c in comments),
            return_exceptions=True,
        )

        now = datetime.now(timezone.utc)
        intent_rows: list[dict] = []
        stack_rows: list[dict] = []

        for comment, parsed in zip(comments, classifications):
            if isinstance(parsed, Exception) or not parsed:
                continue
            company_name = parsed.get("company")
            if not company_name:
                continue
            company = _match_company_by_name(company_name, companies)
            if company is None:
                # Phase 1: skip unknown companies rather than auto-create — keeps the
                # tracked list clean and under the free-tier company budget.
                continue
            comment_url = f"https://news.ycombinator.com/item?id={comment.get('id')}"
            intent_rows.append(
                {
                    "company_id": company.id,
                    "signal_type": "hn_whos_hiring",
                    "source": comment_url,
                    "raw_data": {"text": comment.get("text", "")[:4000]},
                    "extracted": parsed,
                    "confidence": 0.85,
                    "detected_at": now,
                }
            )
            techs = parsed.get("technologies") or []
            if techs:
                stack_rows.append(
                    {
                        "company_id": company.id,
                        "source_type": "hn_whos_hiring",
                        "source_url": comment_url,
                        "technologies": {t: 0.8 for t in techs},
                        "raw_evidence": html_to_text(comment.get("text", ""))[:500],
                        "detected_at": now,
                    }
                )

        return {"intent": intent_rows, "stack": stack_rows}

    async def collect(self, company: Company) -> dict[str, Any]:
        return {"intent": [], "stack": []}
