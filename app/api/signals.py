from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.company import Company
from app.models.intent_signal import IntentSignal
from app.schemas.signal import IntentSignalRead, RecentSignalItem

router = APIRouter(tags=["signals"])


@router.get("/companies/{company_id}/signals", response_model=list[IntentSignalRead])
def list_company_signals(
    company_id: UUID,
    type: str | None = Query(None, alias="type"),
    since: datetime | None = None,
    db: Session = Depends(get_db),
) -> list[IntentSignal]:
    if not db.get(Company, company_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")

    stmt = (
        select(IntentSignal)
        .where(IntentSignal.company_id == company_id)
        .order_by(IntentSignal.detected_at.desc())
    )
    if type:
        stmt = stmt.where(IntentSignal.signal_type == type)
    if since:
        stmt = stmt.where(IntentSignal.detected_at >= since)
    return list(db.execute(stmt).scalars().all())


@router.get("/signals/recent", response_model=list[RecentSignalItem])
def recent_signals(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)) -> list:
    stmt = (
        select(IntentSignal, Company.name, Company.domain)
        .join(Company, Company.id == IntentSignal.company_id)
        .order_by(IntentSignal.detected_at.desc())
        .limit(limit)
    )
    out: list[dict] = []
    for signal, name, domain in db.execute(stmt).all():
        item = RecentSignalItem.model_validate(signal, from_attributes=True).model_dump()
        item["company_name"] = name
        item["company_domain"] = domain
        out.append(item)
    return out
