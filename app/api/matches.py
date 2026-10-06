from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.auth import get_current_user
from app.database import get_db
from app.models.company import Company
from app.models.match import Match
from app.models.user import User
from app.processors.match_engine import refresh_matches_for_user
from app.schemas.match import MatchStatusUpdate, MatchWithCompany

router = APIRouter(prefix="/matches", tags=["matches"])


@router.get("", response_model=list[MatchWithCompany])
def list_matches(
    min_score: float = Query(0, ge=0, le=100),
    min_tech_fit: float = Query(0, ge=0, le=1),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = (
        select(Match)
        .options(joinedload(Match.company).joinedload(Company.score))
        .where(
            Match.user_id == user.id,
            Match.score >= min_score,
            Match.tech_fit >= min_tech_fit,
        )
        .order_by(Match.score.desc())
        .limit(limit)
    )
    results = db.execute(stmt).unique().scalars().all()

    out: list[dict] = []
    for m in results:
        out.append(
            {
                "id": m.id,
                "user_id": m.user_id,
                "company_id": m.company_id,
                "score": m.score,
                "tech_fit": m.tech_fit,
                "intent_score": m.intent_score,
                "top_signals": m.top_signals,
                "status": m.status,
                "matched_at": m.matched_at,
                "company": {
                    "id": m.company.id,
                    "name": m.company.name,
                    "domain": m.company.domain,
                    "careers_url": m.company.careers_url,
                    "ats_type": m.company.ats_type,
                    "ats_slug": m.company.ats_slug,
                    "github_org": m.company.github_org,
                    "app_package_id": m.company.app_package_id,
                    "employee_count": m.company.employee_count,
                    "industry": m.company.industry,
                    "location": m.company.location,
                    "website": m.company.website,
                    "logo_url": m.company.logo_url,
                    "is_active": m.company.is_active,
                    "created_at": m.company.created_at,
                    "updated_at": m.company.updated_at,
                },
                "company_score": (
                    {
                        "intent_score": m.company.score.intent_score,
                        "stack_fingerprint": m.company.score.stack_fingerprint,
                        "signal_count": m.company.score.signal_count,
                        "strongest_signal": m.company.score.strongest_signal,
                        "last_scored_at": m.company.score.last_scored_at,
                    }
                    if m.company.score
                    else None
                ),
            }
        )
    return out


@router.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
def refresh_matches(
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
) -> dict:
    background.add_task(refresh_matches_for_user, user.id)
    return {"status": "scheduled", "user_id": str(user.id)}


@router.patch("/{match_id}", response_model=MatchWithCompany)
def update_match_status(
    match_id: UUID,
    payload: MatchStatusUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Match:
    match = db.get(Match, match_id)
    if not match or match.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Match not found")
    match.status = payload.status
    db.commit()
    db.refresh(match)
    return match
