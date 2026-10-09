"""Aggregates per-company stack_signals into a single fingerprint.

Per technology: take max(confidence) across sources, capped per source type.
"""
from __future__ import annotations

from collections.abc import Iterable

from app.models.stack_signal import StackSignal

# Max confidence per source type, from spec.
SOURCE_CAPS: dict[str, float] = {
    "github": 1.0,
    "ats_job_nlp": 0.9,
    # Owning public Dart repos is strong evidence a company builds in Flutter,
    # but weaker than parsing an actual pubspec.yaml (which scores as "github").
    "github_dart_org": 0.85,
    "wappalyzer": 0.7,
    "blog": 0.8,
    "hn_whos_hiring": 0.8,
    "apk": 0.95,
}


def fingerprint(signals: Iterable[StackSignal]) -> dict[str, float]:
    out: dict[str, float] = {}
    for s in signals:
        cap = SOURCE_CAPS.get(s.source_type, 0.5)
        for tech, conf in (s.technologies or {}).items():
            if not tech:
                continue
            capped = min(float(conf), cap)
            if capped > out.get(tech, 0.0):
                out[tech] = capped
    return out
