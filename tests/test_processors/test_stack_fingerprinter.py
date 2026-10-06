from __future__ import annotations

from types import SimpleNamespace

from app.processors.stack_fingerprinter import SOURCE_CAPS, fingerprint


def _sig(source_type: str, techs: dict[str, float]):
    return SimpleNamespace(source_type=source_type, technologies=techs)


def test_takes_max_confidence_across_sources():
    signals = [
        _sig("github", {"python": 0.9}),
        _sig("ats_job_nlp", {"python": 0.5}),
    ]
    assert fingerprint(signals)["python"] == 0.9


def test_caps_per_source_type():
    signals = [_sig("wappalyzer", {"react": 1.0})]
    # Wappalyzer cap is 0.7 per spec
    assert fingerprint(signals)["react"] == SOURCE_CAPS["wappalyzer"]


def test_unknown_source_defaults_to_half():
    signals = [_sig("unknown_src", {"python": 1.0})]
    assert fingerprint(signals)["python"] == 0.5


def test_empty_input_returns_empty_dict():
    assert fingerprint([]) == {}
