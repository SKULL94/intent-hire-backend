from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, joinedload

from pydantic import BaseModel

from app.auth import get_current_user, require_service_key
from app.config import settings
from app.database import get_db
from app.models.company import Company
from app.models.company_score import CompanyScore
from app.models.job import Job
from app.models.user import User
from app.schemas.company import CompanyCreate, CompanyDetail, CompanyListItem, CompanyRead
from app.utils.email_composer import compose_cold_email
from app.utils.email_finder import extract_from_text, find_via_hunter

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


@router.get("/{company_id}/recruiter-email")
async def get_recruiter_email(
    company_id: UUID,
    db: Session = Depends(get_db),
) -> dict:
    """Find the best available recruiter contact email for a company.

    Strategy (fastest first):
    1. Scan the company's stored job descriptions for embedded email addresses —
       some small companies include a contact address directly in the posting.
    2. Query Hunter.io if HUNTER_API_KEY is configured — returns verified
       addresses indexed from the public web, filtered to engineering contacts.

    Response: `{"email": "...", "first_name": "...", "source": "..."}` or
              `{"email": null, "first_name": null, "source": null}` if nothing
              was found.
    """
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")

    # Step 1: scan stored job descriptions (instant, no external call).
    descriptions = db.execute(
        select(Job.description)
        .where(Job.company_id == company_id, Job.description.is_not(None))
        .order_by(Job.last_seen_at.desc())
        .limit(5)
    ).scalars().all()

    for description in descriptions:
        email = extract_from_text(description)
        if email:
            return {"email": email, "first_name": None, "source": "job_description"}

    # Step 2: Hunter.io (requires API key + company domain).
    if settings.hunter_configured and company.domain:
        email, first_name = await find_via_hunter(company.domain, settings.hunter_api_key)
        if email:
            return {"email": email, "first_name": first_name, "source": "hunter"}

    return {"email": None, "first_name": None, "source": None}


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


class CompanyComposeEmailRequest(BaseModel):
    recruiter_name: str | None = None


@router.post("/{company_id}/compose-email")
async def compose_company_email(
    company_id: UUID,
    body: CompanyComposeEmailRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Generate a 'exploring opportunities' cold email for a company without a specific job."""
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    result = await compose_cold_email(
        user=user,
        company_name=company.name,
        job_title=None,
        job_description=None,
        recruiter_name=body.recruiter_name,
    )
    return result
