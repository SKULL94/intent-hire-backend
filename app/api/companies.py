from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, joinedload

from app.auth import require_service_key
from app.database import get_db
from app.models.company import Company
from app.models.company_score import CompanyScore
from app.schemas.company import CompanyCreate, CompanyDetail, CompanyListItem, CompanyRead

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=list[CompanyListItem])
def list_companies(
    sort: str = Query("intent_score", pattern="^(intent_score|name)$"),
    min_score: float | None = Query(None, ge=0, le=100),
    tech: str | None = Query(None, description="Comma-separated list; AND match"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[Company]:
    stmt = select(Company).options(joinedload(Company.score)).where(Company.is_active.is_(True))

    if min_score is not None:
        stmt = stmt.join(CompanyScore).where(CompanyScore.intent_score >= min_score)

    if tech:
        wanted = [t.strip().lower() for t in tech.split(",") if t.strip()]
        for t in wanted:
            # stack_fingerprint is JSONB mapping tech -> confidence; existence of the key is enough
            stmt = stmt.join(CompanyScore, isouter=False).where(
                CompanyScore.stack_fingerprint.op("?")(t)
            )

    if sort == "name":
        stmt = stmt.order_by(Company.name.asc())
    else:
        stmt = stmt.outerjoin(CompanyScore).order_by(desc(CompanyScore.intent_score))

    stmt = stmt.limit(limit).offset(offset)
    return list(db.execute(stmt).unique().scalars().all())


@router.get("/{company_id}", response_model=CompanyDetail)
def get_company(company_id: UUID, db: Session = Depends(get_db)) -> Company:
    stmt = (
        select(Company)
        .options(
            joinedload(Company.score),
            joinedload(Company.intent_signals),
            joinedload(Company.stack_signals),
        )
        .where(Company.id == company_id)
    )
    company = db.execute(stmt).unique().scalar_one_or_none()
    if not company:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    return company


@router.post(
    "",
    response_model=CompanyRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_service_key)],
)
def create_company(payload: CompanyCreate, db: Session = Depends(get_db)) -> Company:
    exists = (
        db.execute(select(Company).where(Company.name == payload.name)).scalar_one_or_none()
        if not payload.domain
        else db.execute(select(Company).where(Company.domain == payload.domain)).scalar_one_or_none()
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Company already exists")

    company = Company(**payload.model_dump(exclude_unset=True))
    db.add(company)
    db.commit()
    db.refresh(company)
    return company
