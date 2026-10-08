from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.processors.scoring_engine import (
    SIGNAL_WEIGHTS,
    calculate_intent_score,
    calculate_tech_fit,
    compute_match_score,
)


def _signal(signal_type: str, confidence: float, days_old: float, source: str = "test:src"):
    detected = datetime.now(timezone.utc) - timedelta(days=days_old)
    return SimpleNamespace(
        signal_type=signal_type,
        confidence=confidence,
        detected_at=detected,
        source=source,
    )


def test_intent_score_fresh_ats_job_contributes_full_weight():
    signals = [_signal("ats_job", 1.0, 0)]
    score, count, strongest = calculate_intent_score(signals)
    assert count == 1
    assert strongest == "ats_job"
    assert math.isclose(score, SIGNAL_WEIGHTS["ats_job"], rel_tol=1e-6)


def test_intent_score_caps_at_100():
    signals = [_signal("ats_job", 1.0, 0)] * 10 + [_signal("funding", 1.0, 0)] * 10
    score, _, _ = calculate_intent_score(signals)
    assert score == 100.0


def test_intent_score_decays_with_age():
    fresh = calculate_intent_score([_signal("ats_job", 1.0, 0)])[0]
    old = calculate_intent_score([_signal("ats_job", 1.0, 100)])[0]
    assert old < fresh


def test_daily_ats_snapshots_do_not_accumulate():
    """The daily collector re-observes the same open roles; that must not inflate.

    Without snapshot collapsing, 30 nightly runs push `ats_job` (weight 40) past
    the 100 cap, so every actively-hiring company ties at 100 and the ranking
    stops discriminating.
    """
    thirty_nightly_runs = [
        _signal("ats_job", 1.0, days_old=d, source="greenhouse:acme") for d in range(30)
    ]
    score, count, _ = calculate_intent_score(thirty_nightly_runs)

    assert count == 1, "only the latest observation of a snapshot signal should count"
    assert math.isclose(score, SIGNAL_WEIGHTS["ats_job"], rel_tol=1e-6)
    assert score < 100.0


def test_distinct_snapshot_sources_still_both_count():
    signals = [
        _signal("ats_job", 1.0, 0, source="greenhouse:acme"),
        _signal("github_activity", 1.0, 0, source="github:acme:new_repos"),
    ]
    _, count, _ = calculate_intent_score(signals)
    assert count == 2


def test_discrete_events_still_accumulate():
    """Two funding rounds are genuinely more signal than one."""
    one = calculate_intent_score([_signal("funding", 1.0, 0, source="rss:a")])[0]
    two = calculate_intent_score(
        [_signal("funding", 1.0, 0, source="rss:a"), _signal("funding", 1.0, 0, source="rss:b")]
    )[0]
    assert two > one


def test_tech_fit_zero_when_no_overlap():
    assert calculate_tech_fit({"python": 1.0}, {"go": 1.0}) == 0.0


def test_tech_fit_one_when_identical():
    skills = {"python": 1.0, "fastapi": 0.9}
    assert math.isclose(calculate_tech_fit(skills, skills), 1.0, rel_tol=1e-6)


def test_compute_match_score_combines_both():
    # tech_fit dominates per spec weighting
    assert compute_match_score(50.0, 0.5) == (0.4 * 50.0) + (0.6 * 50.0)
