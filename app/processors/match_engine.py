"""Per-user match refresh: tech_fit × intent_score across all active companies."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, joinedload

from app.database import SessionLocal
from app.models.company import Company
from app.models.company_score import CompanyScore
from app.models.intent_signal import IntentSignal
from app.models.job import Job
from app.models.match import Match
from app.models.user import User
from app.processors.scoring_engine import calculate_tech_fit, compute_match_score

log = logging.getLogger(__name__)

TOP_SIGNALS_PER_MATCH = 3
MIN_INTENT_SCORE = 10   # filters companies with only GitHub activity (≈4–5 points)
MIN_TECH_FIT = 0.20     # ~20% cosine overlap; a company with no Flutter/Dart scores 0.0


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

        # Pre-build sets for geo filtering. A company that has ATS jobs but
        # zero India/remote-compatible ones is likely a US/EU on-site employer —
        # no point surfacing it for a Delhi-based candidate.
        companies_with_any_jobs: set = set(
            db.execute(select(Job.company_id).distinct()).scalars()
        )
        companies_with_india_remote: set = set(
            db.execute(
                select(Job.company_id)
                .where(
                    or_(
                        Job.is_remote.is_(True),
                        Job.location_normalized.ilike("%india%"),
                        Job.location_normalized.ilike("%remote%"),
                    )
                )
                .distinct()
            ).scalars()
        )

        written = 0
        skipped_ids: set = set()
        now = datetime.now(timezone.utc)
        for company in companies:
            score: CompanyScore | None = company.score
            if score is None:
                continue

            # Drop companies with too little hiring signal (GitHub activity alone
            # gives ≈4–5 points — not enough to mean they are actually hiring).
            if score.intent_score < MIN_INTENT_SCORE:
                skipped_ids.add(company.id)
                continue

            # Drop companies that have jobs in the DB but none accessible from
            # India (no remote flag, no India location). Companies without any
            # jobs yet (discovered via GitHub/HN only) pass through — we have
            # no geo evidence to exclude them.
            if (
                company.id in companies_with_any_jobs
                and company.id not in companies_with_india_remote
            ):
                skipped_ids.add(company.id)
                continue

            stack = score.stack_fingerprint or {}

            # Require at least one of the user's skills to exist in the company
            # stack fingerprint. Pure cosine similarity returns 0.0 for a
            # company with no overlapping tech, but that 0.0 is still written as
            # a match row. This guard prevents those rows from being created.
            if not any(skill in stack for skill in (user.skills or {})):
                skipped_ids.add(company.id)
                continue

            tech_fit = calculate_tech_fit(user.skills or {}, stack)

            if tech_fit < MIN_TECH_FIT:
                skipped_ids.add(company.id)
                continue

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

        # Delete any pre-existing matches for companies that no longer qualify,
        # so stale rows don't linger until the next manual refresh.
        if skipped_ids:
            from sqlalchemy import delete
            db.execute(
                delete(Match).where(
                    Match.user_id == user.id,
                    Match.company_id.in_(skipped_ids),
                )
            )

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
