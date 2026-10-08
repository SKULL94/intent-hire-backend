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

# Signal types that describe *current state* rather than a discrete event.
#
# "This company has 40 open engineering roles" is a snapshot: the daily collector
# re-observes the same fact and writes a new row each run. Summing those rows
# would make the score a function of how long we have been watching — `ats_job`
# alone (weight 40) crosses the 100 cap after three daily runs, at which point
# every actively-hiring company ties at 100 and the ranking carries no
# information. For these types only the most recent observation per source
# counts, so the score reflects what is true now.
#
# Everything else (funding rounds, news items, HN posts) is a real event:
# two funding rounds genuinely are more signal than one, so those accumulate.
SNAPSHOT_SIGNAL_TYPES: frozenset[str] = frozenset({"ats_job", "github_activity"})


def _scoreable(signals: Iterable[IntentSignal]) -> list[IntentSignal]:
    """Collapse snapshot signals to the latest observation per (type, source)."""
    latest: dict[tuple[str, str | None], IntentSignal] = {}
    events: list[IntentSignal] = []

    for s in signals:
        if s.signal_type not in SNAPSHOT_SIGNAL_TYPES:
            events.append(s)
            continue
        key = (s.signal_type, s.source)
        seen = latest.get(key)
        if seen is None or _detected_at(s) > _detected_at(seen):
            latest[key] = s

    return events + list(latest.values())


def _detected_at(s: IntentSignal) -> datetime:
    ts = s.detected_at
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


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

    for s in _scoreable(signals):
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
