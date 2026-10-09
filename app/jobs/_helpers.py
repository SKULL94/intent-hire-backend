"""Shared helpers for standalone job scripts."""
from __future__ import annotations

import logging
from collections.abc import Iterable
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
    require_ats: bool = False,
    require_github: bool = False,
    require_domain: bool = False,
    limit: int | None = None,
) -> list[Company]:
    stmt = select(Company).where(Company.is_active.is_(True))
    if company_id is not None:
        stmt = stmt.where(Company.id == company_id)
    if require_ats:
        stmt = stmt.where(Company.ats_type.is_not(None), Company.ats_slug.is_not(None))
    if require_github:
        stmt = stmt.where(Company.github_org.is_not(None))
    if require_domain:
        stmt = stmt.where(Company.domain.is_not(None))
    if limit is None:
        limit = settings.max_companies_per_run
    stmt = stmt.limit(limit)
    return list(db.execute(stmt).scalars())


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
