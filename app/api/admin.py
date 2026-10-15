from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth import require_service_key
from app.database import get_db
from app.models.intent_signal import IntentSignal
from app.models.job import Job

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_service_key)])

CollectorName = Literal["adzuna", "cleanup"]


class TriggerBody(BaseModel):
    collector: CollectorName
    company_id: UUID | None = None


def _invoke(name: CollectorName, company_id: UUID | None) -> None:
    # Each run_* module exposes an async `main(company_id=None)` entrypoint.
    import importlib

    module_map = {
        "adzuna": "app.jobs.run_adzuna",
        "cleanup": "app.jobs.run_cleanup",
    }
    module = importlib.import_module(module_map[name])
    asyncio.run(module.main(company_id=company_id))


@router.post("/collectors/trigger", status_code=status.HTTP_202_ACCEPTED)
def trigger_collector(body: TriggerBody, background: BackgroundTasks) -> dict:
    background.add_task(_invoke, body.collector, body.company_id)
    return {"status": "scheduled", "collector": body.collector}


@router.get("/collectors/status")
def collector_status(db: Session = Depends(get_db)) -> dict:
    stmt = (
        select(IntentSignal.signal_type, func.max(IntentSignal.detected_at))
        .group_by(IntentSignal.signal_type)
    )
    rows = db.execute(stmt).all()
    return {
        "last_run": {row[0]: row[1].isoformat() if row[1] else None for row in rows},
    }


@router.delete("/data/stale", status_code=status.HTTP_200_OK)
def purge_stale_data(
    jobs_older_than_days: int = Query(14, ge=1, le=365, description="Delete jobs last seen more than N days ago"),
    signals_older_than_days: int = Query(60, ge=1, le=730, description="Delete intent signals older than N days"),
    db: Session = Depends(get_db),
) -> dict:
    """Hard-delete postings not seen recently and old hiring signals.

    Postings are kept only as evidence that a company hires Flutter, so a long
    tail of them adds nothing once newer evidence exists for the same company.
    Hiring signals ("about to hire") expire by nature: a funding round from two
    years ago predicts nothing today.
    """
    now = datetime.now(timezone.utc)
    job_cutoff = now - timedelta(days=jobs_older_than_days)
    signal_cutoff = now - timedelta(days=signals_older_than_days)

    jobs_result = db.execute(
        delete(Job).where(Job.last_seen_at < job_cutoff)
    )
    signals_result = db.execute(
        delete(IntentSignal).where(IntentSignal.detected_at < signal_cutoff)
    )
    db.commit()

    return {
        "jobs_deleted": jobs_result.rowcount,
        "signals_deleted": signals_result.rowcount,
        "job_cutoff": job_cutoff.isoformat(),
        "signal_cutoff": signal_cutoff.isoformat(),
    }
