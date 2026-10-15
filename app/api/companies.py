"""The only question this service answers.

Which companies hire Flutter developers, are reachable from Delhi NCR (or
remote), and which of those are about to hire?

An opening is deliberately not required. "This company builds in Flutter" is a
durable fact written into their shipped product; "this company has a vacancy
today" is a perishable one that every job board already sells badly.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.auth import require_service_key
from app.database import get_db
from app.models.company import Company
from app.models.intent_signal import IntentSignal
from app.models.job import Job
from app.models.stack_signal import StackSignal
from app.schemas.company import CompanyCreate, CompanyDetail, CompanyListItem, CompanyRead
from app.utils.job_parser import INDIA_REACHABLE_LOCATIONS

router = APIRouter(prefix="/companies", tags=["companies"])

# Evidence of Flutter is evidence of either key.
FLUTTER_KEYS = ("flutter", "dart")

# A funding round or expansion announcement older than this has already played
# out — the hiring it implied either happened or did not.
HIRING_SIGNAL_WINDOW = timedelta(days=90)

# Signal types that mean "about to hire" rather than "is hiring now".
LEADING_SIGNAL_TYPES = ("funding", "news")


def _flutter_company_ids(db: Session) -> set[UUID]:
    """Companies with stack evidence naming Flutter or Dart."""
    conditions = [StackSignal.technologies.op("?")(key) for key in FLUTTER_KEYS]
    return set(
        db.execute(
            select(StackSignal.company_id).where(or_(*conditions)).distinct()
        ).scalars()
    )


def _ncr_or_remote_company_ids(db: Session) -> set[UUID]:
    """Companies with at least one posting reachable from Delhi NCR or remote.

    Match on the canonical key set, never a substring: the normalizer emits
    city keys (`delhi_ncr`, `bengaluru`), so a `LIKE '%india%'` test silently
    drops every Indian city.
    """
    return set(
        db.execute(
            select(Job.company_id)
            .where(
                or_(
                    Job.is_remote.is_(True),
                    Job.location_normalized.in_(INDIA_REACHABLE_LOCATIONS),
                )
            )
            .distinct()
        ).scalars()
    )


def _hiring_soon_company_ids(db: Session) -> set[UUID]:
    """Companies with a recent leading signal that they are about to hire."""
    cutoff = datetime.now(timezone.utc) - HIRING_SIGNAL_WINDOW
    return set(
        db.execute(
            select(IntentSignal.company_id)
            .where(
                IntentSignal.signal_type.in_(LEADING_SIGNAL_TYPES),
                IntentSignal.detected_at >= cutoff,
            )
            .distinct()
        ).scalars()
    )


@router.get("", response_model=list[CompanyListItem])
def list_companies(
    flutter_only: bool = Query(True, description="Require Flutter/Dart stack evidence"),
    ncr_or_remote: bool = Query(True, description="Require an NCR or remote posting"),
    hiring_soon: bool = Query(False, description="Require a funding/expansion signal in the last 90 days"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[Company]:
    stmt = select(Company).where(Company.is_active.is_(True))

    for enabled, ids in (
        (flutter_only, _flutter_company_ids),
        (ncr_or_remote, _ncr_or_remote_company_ids),
        (hiring_soon, _hiring_soon_company_ids),
    ):
        if enabled:
            matching = ids(db)
            if not matching:
                return []
            stmt = stmt.where(Company.id.in_(matching))

    stmt = stmt.order_by(Company.name.asc()).limit(limit).offset(offset)
    return list(db.execute(stmt).unique().scalars().all())


@router.get("/{company_id}", response_model=CompanyDetail)
def get_company(company_id: UUID, db: Session = Depends(get_db)) -> CompanyDetail:
    stmt = (
        select(Company)
        .options(
            joinedload(Company.intent_signals),
            joinedload(Company.stack_signals),
        )
        .where(Company.id == company_id)
    )
    company = db.execute(stmt).unique().scalar_one_or_none()
    if not company:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")

    # Collapse re-observations before returning them.
    #
    # Every collector run appends a row, so a company seen on ten days carries
    # ten identical "Hired for Flutter" observations. They are the same fact
    # re-observed, not ten pieces of evidence, and listing them all makes the
    # detail screen read like a log file.
    detail = CompanyDetail.model_validate(company)
    detail.stack_signals = _latest_per(
        detail.stack_signals, key=lambda e: (e.source_type, e.source_url)
    )
    detail.intent_signals = _latest_per(
        detail.intent_signals, key=lambda s: (s.signal_type, s.source)
    )
    return detail


def _latest_per(rows: list, key) -> list:
    """Newest row per `key`, newest group first."""
    newest: dict = {}
    for row in rows:
        k = key(row)
        seen = newest.get(k)
        if seen is None or row.detected_at > seen.detected_at:
            newest[k] = row
    return sorted(newest.values(), key=lambda r: r.detected_at, reverse=True)


@router.post(
    "",
    response_model=CompanyRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_service_key)],
)
def create_company(payload: CompanyCreate, db: Session = Depends(get_db)) -> Company:
    exists = (
        db.execute(
            select(Company).where(func.lower(Company.domain) == payload.domain.lower())
        ).scalar_one_or_none()
        if payload.domain
        else db.execute(
            select(Company).where(Company.name == payload.name)
        ).scalar_one_or_none()
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Company already exists")

    company = Company(**payload.model_dump(exclude_unset=True))
    db.add(company)
    db.commit()
    db.refresh(company)
    return company
