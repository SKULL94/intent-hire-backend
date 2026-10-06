from __future__ import annotations

from app.collectors.ats.greenhouse import GreenhouseAdapter


def test_normalize_minimal_job():
    raw = {
        "id": 1234,
        "title": "Senior Backend Engineer",
        "location": {"name": "Bangalore"},
        "departments": [{"name": "Engineering"}],
        "content": "<p>Python, FastAPI, Postgres required.</p>",
        "updated_at": "2026-10-01T10:00:00Z",
        "absolute_url": "https://boards.greenhouse.io/x/jobs/1234",
    }
    out = GreenhouseAdapter._normalize(raw)
    assert out["title"] == "Senior Backend Engineer"
    assert out["location"] == "Bangalore"
    assert out["department"] == "Engineering"
    assert "FastAPI" in out["description"]
    assert out["url"].endswith("/1234")
    assert out["external_id"] == "1234"


def test_normalize_missing_fields_doesnt_crash():
    raw = {"id": 9, "title": "Dev"}
    out = GreenhouseAdapter._normalize(raw)
    assert out["title"] == "Dev"
    assert out["location"] is None
    assert out["department"] is None
    assert out["external_id"] == "9"
