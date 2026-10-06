from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.intent_signal import IntentSignal

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:  # noqa: BLE001 - we want to downgrade not raise
        db_status = "unreachable"
    return {"status": "ok", "db": db_status}


@router.get("/health/collectors")
def collectors_health(db: Session = Depends(get_db)) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    stmt = (
        select(IntentSignal.signal_type, func.count().label("n"))
        .where(IntentSignal.detected_at >= cutoff)
        .group_by(IntentSignal.signal_type)
    )
    counts = {row.signal_type: row.n for row in db.execute(stmt).all()}

    last_run_stmt = (
        select(IntentSignal.signal_type, func.max(IntentSignal.detected_at).label("last"))
        .group_by(IntentSignal.signal_type)
    )
    last_run = {
        row.signal_type: row.last.isoformat() if row.last else None
        for row in db.execute(last_run_stmt).all()
    }
    return {
        "last_run": last_run,
        "signals_last_24h": sum(counts.values()),
        "by_type_last_24h": counts,
    }
