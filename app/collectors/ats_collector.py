"""Per-company ATS collector.

1. Resolve adapter by `company.ats_type`.
2. Fetch jobs via the adapter.
3. Insert one `intent_signal` row summarizing the fetch (count-based confidence).
4. For each job description, call Claude Haiku to extract tech → `stack_signals(ats_job_nlp)`.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.collectors.ats.registry import get_adapter
from app.collectors.base import BaseCollector
from app.models.company import Company
from app.processors.llm_classifier import extract_stack

log = logging.getLogger(__name__)

MAX_JOBS_FOR_STACK_EXTRACTION = 20  # cap LLM calls per company


class ATSCollector(BaseCollector):
    def source_name(self) -> str:
        return "ats"

    async def collect(self, company: Company) -> dict[str, Any]:
        adapter = get_adapter(company.ats_type)
        if adapter is None or not company.ats_slug:
            return {"intent": [], "stack": []}

        try:
            await self.rate_limiter.acquire(adapter.ats_name())
            jobs = await adapter.fetch_jobs(self.client, company.ats_slug)
        except Exception:  # noqa: BLE001
            log.exception("ATS fetch failed for %s via %s", company.name, adapter.ats_name())
            return {"intent": [], "stack": []}

        if not jobs:
            return {"intent": [], "stack": []}

        count = len(jobs)
        confidence = min(1.0, count / 5.0)
        now = datetime.now(timezone.utc)

        intent_rows = [
            {
                "company_id": company.id,
                "signal_type": "ats_job",
                "source": f"{adapter.ats_name()}:{company.ats_slug}",
                "raw_data": {"job_count": count, "ats": adapter.ats_name()},
                "extracted": {
                    "job_titles": [j.get("title") for j in jobs[:50]],
                    "job_count": count,
                },
                "confidence": confidence,
                "detected_at": now,
            }
        ]

        # LLM stack extraction, bounded.
        extracted = await asyncio.gather(
            *(
                extract_stack(company.name, job.get("description", "")[:4000])
                for job in jobs[:MAX_JOBS_FOR_STACK_EXTRACTION]
                if job.get("description")
            ),
            return_exceptions=True,
        )

        stack_rows: list[dict] = []
        for job, result in zip(jobs[:MAX_JOBS_FOR_STACK_EXTRACTION], extracted):
            if isinstance(result, Exception) or not result:
                continue
            technologies = result.get("technologies") or {}
            if not technologies:
                continue
            stack_rows.append(
                {
                    "company_id": company.id,
                    "source_type": "ats_job_nlp",
                    "source_url": job.get("url"),
                    "technologies": technologies,
                    "raw_evidence": (job.get("description") or "")[:500],
                    "detected_at": now,
                }
            )

        return {"intent": intent_rows, "stack": stack_rows}
