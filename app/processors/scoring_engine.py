"""Intent scoring + match-score computation.

Signals decay exponentially; each type has a fixed weight. Scores are capped at 100.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.company_score import CompanyScore
from app.models.intent_signal import IntentSignal
from app.models.stack_signal import StackSignal
from app.processors.stack_fingerprinter import fingerprint

SIGNAL_WEIGHTS: dict[str, float] = {
    "ats_job": 40,
    "funding": 30,
    "hn_whos_hiring": 15,
    "news": 10,
    "github_activity": 5,
}

DECAY_RATES: dict[str, float] = {  # exponential: value * e^(-rate * days_old)
    "ats_job": 0.05,
    "funding": 0.02,
    "hn_whos_hiring": 0.04,
    "news": 0.04,
    "github_activity": 0.03,
}


def _days_old(ts: datetime) -> float:
    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = now - ts
    return max(delta.total_seconds() / 86400.0, 0.0)


def calculate_intent_score(signals: Iterable[IntentSignal]) -> tuple[float, int, str | None]:
    """Return (score, signal_count, strongest_signal_type)."""
    total = 0.0
    strongest_contrib = 0.0
    strongest: str | None = None
    count = 0

    for s in signals:
        weight = SIGNAL_WEIGHTS.get(s.signal_type)
        rate = DECAY_RATES.get(s.signal_type)
        if weight is None or rate is None:
            continue
        decay = math.exp(-rate * _days_old(s.detected_at))
        contrib = weight * float(s.confidence or 0.0) * decay
        total += contrib
        count += 1
        if contrib > strongest_contrib:
            strongest_contrib = contrib
            strongest = s.signal_type

    return min(total, 100.0), count, strongest


def calculate_tech_fit(user_skills: dict[str, float], company_stack: dict[str, float]) -> float:
    if not user_skills or not company_stack:
        return 0.0
    all_techs = set(user_skills) | set(company_stack)
    u = [float(user_skills.get(t, 0.0)) for t in all_techs]
    c = [float(company_stack.get(t, 0.0)) for t in all_techs]
    dot = sum(a * b for a, b in zip(u, c))
    mag_u = math.sqrt(sum(x * x for x in u))
    mag_c = math.sqrt(sum(x * x for x in c))
    if mag_u == 0 or mag_c == 0:
        return 0.0
    return dot / (mag_u * mag_c)


def compute_match_score(intent_score: float, tech_fit: float) -> float:
    # Weighted toward tech fit — a hiring company in the wrong stack is useless.
    return (0.4 * intent_score) + (0.6 * tech_fit * 100.0)


def rescore_company(db: Session, company: Company) -> CompanyScore:
    """(Re)compute `company_scores` row for one company. Caller commits."""
    intent_signals = list(
        db.execute(select(IntentSignal).where(IntentSignal.company_id == company.id)).scalars()
    )
    stack_signals = list(
        db.execute(select(StackSignal).where(StackSignal.company_id == company.id)).scalars()
    )

    intent, count, strongest = calculate_intent_score(intent_signals)
    stack = fingerprint(stack_signals)

    score = company.score
    if score is None:
        score = CompanyScore(company_id=company.id)
        db.add(score)

    score.intent_score = intent
    score.signal_count = count
    score.strongest_signal = strongest
    score.stack_fingerprint = stack
    score.last_scored_at = datetime.now(timezone.utc)
    return score


def rescore_all(db: Session) -> int:
    companies = list(db.execute(select(Company).where(Company.is_active.is_(True))).scalars())
    for c in companies:
        rescore_company(db, c)
    db.commit()
    return len(companies)
