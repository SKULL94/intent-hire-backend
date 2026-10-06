"""Per-user match refresh: tech_fit × intent_score across all active companies."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, joinedload

from app.database import SessionLocal
from app.models.company import Company
from app.models.company_score import CompanyScore
from app.models.intent_signal import IntentSignal
from app.models.match import Match
from app.models.user import User
from app.processors.scoring_engine import calculate_tech_fit, compute_match_score

log = logging.getLogger(__name__)

TOP_SIGNALS_PER_MATCH = 3


def _top_signals_for(db: Session, company_id: UUID) -> list[dict]:
    stmt = (
        select(IntentSignal)
        .where(IntentSignal.company_id == company_id)
        .order_by(IntentSignal.detected_at.desc())
        .limit(TOP_SIGNALS_PER_MATCH)
    )
    return [
        {
            "signal_type": s.signal_type,
            "source": s.source,
            "confidence": float(s.confidence or 0.0),
            "detected_at": s.detected_at.isoformat() if s.detected_at else None,
        }
        for s in db.execute(stmt).scalars()
    ]


def refresh_matches_for_user(user_id: UUID) -> int:
    """Recompute all matches for one user. Returns number of matches written.

    Called from a FastAPI background task — opens its own session.
    """
    db: Session = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            log.warning("refresh_matches: user %s not found", user_id)
            return 0

        stmt = (
            select(Company)
            .options(joinedload(Company.score))
            .where(Company.is_active.is_(True))
        )
        companies = db.execute(stmt).unique().scalars().all()

        written = 0
        now = datetime.now(timezone.utc)
        for company in companies:
            score: CompanyScore | None = company.score
            if score is None:
                continue
            tech_fit = calculate_tech_fit(user.skills or {}, score.stack_fingerprint or {})
            match_score = compute_match_score(score.intent_score, tech_fit)

            top_signals = _top_signals_for(db, company.id)

            stmt = (
                pg_insert(Match)
                .values(
                    user_id=user.id,
                    company_id=company.id,
                    score=match_score,
                    tech_fit=tech_fit,
                    intent_score=score.intent_score,
                    top_signals=top_signals,
                    matched_at=now,
                )
                .on_conflict_do_update(
                    constraint="uq_matches_user_company",
                    set_={
                        "score": match_score,
                        "tech_fit": tech_fit,
                        "intent_score": score.intent_score,
                        "top_signals": top_signals,
                        "matched_at": now,
                        "updated_at": now,
                    },
                )
            )
            db.execute(stmt)
            written += 1

        db.commit()
        return written
    finally:
        db.close()


def refresh_all_matches() -> int:
    """Recompute matches for every active user."""
    db: Session = SessionLocal()
    try:
        user_ids = [u.id for u in db.execute(select(User).where(User.is_active.is_(True))).scalars()]
    finally:
        db.close()

    total = 0
    for uid in user_ids:
        total += refresh_matches_for_user(uid)
    return total
