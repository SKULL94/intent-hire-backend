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


def _signal(signal_type: str, confidence: float, days_old: float):
    detected = datetime.now(timezone.utc) - timedelta(days=days_old)
    return SimpleNamespace(signal_type=signal_type, confidence=confidence, detected_at=detected)


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


def test_tech_fit_zero_when_no_overlap():
    assert calculate_tech_fit({"python": 1.0}, {"go": 1.0}) == 0.0


def test_tech_fit_one_when_identical():
    skills = {"python": 1.0, "fastapi": 0.9}
    assert math.isclose(calculate_tech_fit(skills, skills), 1.0, rel_tol=1e-6)


def test_compute_match_score_combines_both():
    # tech_fit dominates per spec weighting
    assert compute_match_score(50.0, 0.5) == (0.4 * 50.0) + (0.6 * 50.0)
