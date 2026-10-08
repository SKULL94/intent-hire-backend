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
from app.utils.role_filter import is_technical_role

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

        # Stack extraction runs only over technical roles. A sales or marketing
        # posting yields the company's product vocabulary and its sales tooling,
        # not its engineering stack — see app/utils/role_filter.
        stack_jobs = [
            job
            for job in jobs
            if job.get("description") and is_technical_role(job.get("title"))
        ][:MAX_JOBS_FOR_STACK_EXTRACTION]

        log.info(
            "%s: %d of %d open roles are technical; extracting stack from %d",
            company.name,
            sum(1 for j in jobs if is_technical_role(j.get("title"))),
            count,
            len(stack_jobs),
        )

        # LLM stack extraction, bounded.
        extracted = await asyncio.gather(
            *(extract_stack(company.name, job["description"][:4000]) for job in stack_jobs),
            return_exceptions=True,
        )

        stack_rows: list[dict] = []
        for job, result in zip(stack_jobs, extracted):
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
