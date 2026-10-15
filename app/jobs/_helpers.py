"""Shared helpers for standalone job scripts."""
from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models.company import Company
from app.models.intent_signal import IntentSignal
from app.models.job import Job
from app.models.stack_signal import StackSignal
from app.utils.job_parser import TITLE_CONFIDENCE

log = logging.getLogger(__name__)


def configure_job_logging() -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def select_companies(
    db: Session,
    *,
    company_id: UUID | None,
    require_github: bool = False,
    require_domain: bool = False,
    limit: int | None = None,
) -> list[Company]:
    stmt = select(Company).where(Company.is_active.is_(True))
    if company_id is not None:
        stmt = stmt.where(Company.id == company_id)
    if require_github:
        stmt = stmt.where(Company.github_org.is_not(None))
    if require_domain:
        stmt = stmt.where(Company.domain.is_not(None))
    if limit is None:
        limit = settings.max_companies_per_run
    stmt = stmt.limit(limit)
    return list(db.execute(stmt).scalars())


def _title_grade(techs: dict[str, Any], tech: str) -> bool:
    """True when `tech` was found in the posting's title, not just its body."""
    try:
        return float(techs.get(tech) or 0.0) >= TITLE_CONFIDENCE
    except (TypeError, ValueError):
        return False


def synthesize_signals_from_jobs(
    job_rows: Iterable[dict[str, Any]],
    source: str,
) -> tuple[list[dict], list[dict]]:
    """Derive company-level Flutter evidence + hiring signals from postings.

    Adzuna fills the `jobs` table but produces no `stack_signals`, and stack
    evidence is what makes a company answer "does this company hire Flutter".
    This turns the postings into that evidence, so a company found only through
    a job feed still lands in the company list.

    Evidence must be **title-grade**. A posting whose body merely mentions
    Flutter is not evidence the company builds in it: measured over one run,
    body-only matches produced Airbnb, Cognizant, McAfee and Netgear as
    "Flutter companies", and in Zenoti's case the matched text was HTML
    boilerplate. Requiring the technology in the *title* cut 42 companies of
    noise and lost almost nothing real — a company that hires Flutter
    developers eventually posts a role with Flutter in the title.
    """
    now = datetime.now(timezone.utc)
    by_company: dict[Any, list[dict]] = defaultdict(list)

    for job in job_rows:
        techs = job.get("technologies") or {}
        if _title_grade(techs, "flutter") or _title_grade(techs, "dart"):
            by_company[job["company_id"]].append(job)

    intent_rows: list[dict] = []
    stack_rows: list[dict] = []

    for company_id, flutter_jobs in by_company.items():
        count = len(flutter_jobs)
        # Pre-filtered Flutter/Dart jobs: even 1 is meaningful evidence,
        # unlike the ATS collector which counts ALL job types. Use /2 so
        # that 2 postings → full confidence rather than needing 5.
        confidence = min(1.0, count / 2.0)

        intent_rows.append(
            {
                "company_id": company_id,
                "signal_type": "ats_job",
                "source": f"{source}:flutter_jobs",
                "raw_data": {"job_count": count, "source": source},
                "extracted": {
                    "job_titles": [j.get("title") for j in flutter_jobs[:20]],
                    "job_count": count,
                },
                "confidence": confidence,
                "detected_at": now,
            }
        )

        # Aggregate per-tech max confidence across all Flutter jobs for this company.
        merged: dict[str, float] = {}
        for job in flutter_jobs:
            for tech, conf in (job.get("technologies") or {}).items():
                try:
                    merged[tech] = max(merged.get(tech, 0.0), float(conf))
                except (TypeError, ValueError):
                    pass

        if merged:
            stack_rows.append(
                {
                    "company_id": company_id,
                    "source_type": "ats_job_nlp",
                    "source_url": None,
                    "technologies": merged,
                    "raw_evidence": (
                        f"Synthesised from {count} {source} Flutter/Dart postings"
                    ),
                    "detected_at": now,
                }
            )

    return intent_rows, stack_rows


def persist_intent(db: Session, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    for r in rows:
        db.add(IntentSignal(**r))
        count += 1
    return count


def persist_stack(db: Session, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    for r in rows:
        db.add(StackSignal(**r))
        count += 1
    return count


def persist_jobs(db: Session, rows: Iterable[dict[str, Any]]) -> tuple[int, int]:
    """Upsert postings on (source, external_id). Returns (written, skipped).

    Unlike signals, a posting is a thing that persists and is re-seen on every
    run. Inserting blindly would multiply the same role by the number of times
    we have collected it. `last_seen_at` advancing is also what lets a future
    pass notice a role has disappeared, which is a hiring signal of its own.
    """
    written = skipped = 0
    for r in rows:
        if not r.get("external_id") or not r.get("title"):
            skipped += 1
            continue
        stmt = (
            pg_insert(Job)
            .values(**r)
            .on_conflict_do_update(
                constraint="uq_jobs_source_external_id",
                set_={
                    "title": r.get("title"),
                    "url": r.get("url"),
                    "department": r.get("department"),
                    "description": r.get("description"),
                    "location_raw": r.get("location_raw"),
                    "location_normalized": r.get("location_normalized"),
                    "is_remote": r.get("is_remote"),
                    "technologies": r.get("technologies"),
                    "min_years_experience": r.get("min_years_experience"),
                    "salary_min": r.get("salary_min"),
                    "salary_max": r.get("salary_max"),
                    "contract_time": r.get("contract_time"),
                    "posted_at": r.get("posted_at"),
                    "last_seen_at": r.get("last_seen_at"),
                },
            )
        )
        db.execute(stmt)
        written += 1
    return written, skipped
