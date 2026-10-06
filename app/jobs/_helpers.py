"""Shared helpers for standalone job scripts."""
from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.company import Company
from app.models.intent_signal import IntentSignal
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
