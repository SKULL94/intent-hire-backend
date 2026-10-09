"""Job-level search: the endpoint that answers "Flutter, Delhi NCR, 3 years".

`/matches` ranks *companies* by hiring intent against a user's whole stack.
That cannot answer a question about one technology in one city, because
`tech_fit` is a cosine over the union of both stacks — a company using Flutter
among fifty technologies scores low against a Flutter-only profile even though
the role is a perfect fit.

This endpoint filters postings directly instead.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.company import Company
from app.models.company_score import CompanyScore
from app.models.job import Job
from app.schemas.job import JobFacets, JobRead

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Keys produced by app.utils.job_parser.normalize_location.
LOCATION_KEYS = [
    "delhi_ncr",
    "bengaluru",
    "mumbai",
    "pune",
    "hyderabad",
    "chennai",
    "kolkata",
    "ahmedabad",
    "india_other",
    "remote",
]


def _apply_filters(
    stmt,
    *,
    tech: list[str] | None,
    location: list[str] | None,
    remote: bool | None,
    max_years: int | None,
    min_salary: float | None,
    search: str | None,
):
    if tech:
        # `?|` is "has any of these keys". Matching ANY rather than ALL is
        # deliberate: a Flutter role that happens not to list Dart explicitly
        # is still a Flutter role.
        #
        # The operand must be a postgresql.array: `jsonb ?| text[]` is the only
        # form Postgres defines, and passing a plain Python list makes
        # SQLAlchemy render it as jsonb, which fails with "operator does not
        # exist: jsonb ?| jsonb".
        stmt = stmt.where(Job.technologies.has_any(array(tech)))

    if location or remote:
        clauses = []
        if location:
            clauses.append(Job.location_normalized.in_(location))
        if remote:
            # Remote is orthogonal to city: a "Remote, Delhi" posting should
            # appear for someone filtering either way.
            clauses.append(Job.is_remote.is_(True))
        stmt = stmt.where(or_(*clauses))
    elif remote is False:
        stmt = stmt.where(or_(Job.is_remote.is_(False), Job.is_remote.is_(None)))

    if max_years is not None:
        # A posting that never states a requirement is kept. Most do not state
        # one, and dropping them would hide the majority of the board.
        stmt = stmt.where(
            or_(
                Job.min_years_experience.is_(None),
                Job.min_years_experience <= max_years,
            )
        )

    if min_salary is not None:
        stmt = stmt.where(Job.salary_min >= min_salary)

    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(Job.title.ilike(pattern), Job.description.ilike(pattern))
        )

    return stmt


@router.get("", response_model=list[JobRead])
def list_jobs(
    tech: list[str] | None = Query(
        None, description="Technology keys, e.g. tech=flutter&tech=dart. Matches ANY."
    ),
    location: list[str] | None = Query(
        None, description=f"Normalized location keys. One of: {', '.join(LOCATION_KEYS)}"
    ),
    remote: bool | None = Query(None, description="true = include remote roles"),
    max_years: int | None = Query(
        None, ge=0, le=20, description="Max years of experience required"
    ),
    min_salary: float | None = Query(None, ge=0),
    search: str | None = Query(None, min_length=2, max_length=100),
    sort: str = Query("recent", pattern="^(recent|intent|salary)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = (
        select(Job, CompanyScore.intent_score)
        .join(Company, Company.id == Job.company_id)
        .outerjoin(CompanyScore, CompanyScore.company_id == Company.id)
        .options(joinedload(Job.company))
    )
    stmt = _apply_filters(
        stmt,
        tech=tech,
        location=location,
        remote=remote,
        max_years=max_years,
        min_salary=min_salary,
        search=search,
    )

    if sort == "intent":
        stmt = stmt.order_by(CompanyScore.intent_score.desc().nullslast())
    elif sort == "salary":
        stmt = stmt.order_by(Job.salary_max.desc().nullslast())
    else:
        stmt = stmt.order_by(Job.posted_at.desc().nullslast(), Job.last_seen_at.desc())

    rows = db.execute(stmt.limit(limit).offset(offset)).unique().all()

    out: list[dict] = []
    for job, intent_score in rows:
        out.append(
            {
                "id": job.id,
                "company_id": job.company_id,
                "source": job.source,
                "title": job.title,
                "url": job.url,
                "department": job.department,
                "description": job.description,
                "location_raw": job.location_raw,
                "location_normalized": job.location_normalized,
                "is_remote": job.is_remote,
                "technologies": job.technologies or {},
                "min_years_experience": job.min_years_experience,
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
                "contract_time": job.contract_time,
                "posted_at": job.posted_at,
                "last_seen_at": job.last_seen_at,
                "company": job.company,
                "company_intent_score": intent_score,
            }
        )
    return out


@router.get("/facets", response_model=JobFacets)
def job_facets(
    tech: list[str] | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    """Counts per location and technology, so the client can show how many
    results a filter would return before the user applies it."""
    base = select(Job)
    if tech:
        base = base.where(Job.technologies.has_any(array(tech)))

    total = db.execute(
        select(func.count()).select_from(base.subquery())
    ).scalar_one()

    by_location = {
        key: count
        for key, count in db.execute(
            select(Job.location_normalized, func.count())
            .where(Job.location_normalized.is_not(None))
            .where(Job.technologies.has_any(array(tech)) if tech else True)
            .group_by(Job.location_normalized)
            .order_by(func.count().desc())
        ).all()
    }

    # jsonb_object_keys over the filtered set: which technologies actually
    # appear, so the UI never offers a chip that returns nothing.
    tech_key = func.jsonb_object_keys(Job.technologies).label("k")
    by_technology = {
        key: count
        for key, count in db.execute(
            select(tech_key, func.count())
            .select_from(Job)
            .group_by(tech_key)
            .order_by(func.count().desc())
            .limit(40)
        ).all()
    }

    remote_count = db.execute(
        select(func.count())
        .select_from(Job)
        .where(Job.is_remote.is_(True))
        .where(Job.technologies.has_any(array(tech)) if tech else True)
    ).scalar_one()

    return {
        "total": total,
        "by_location": by_location,
        "by_technology": by_technology,
        "remote": remote_count,
    }
