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

CollectorName = Literal["ats", "rss", "github", "hn", "wappalyzer", "scoring", "himalayas", "jobicy", "weworkremotely"]


class TriggerBody(BaseModel):
    collector: CollectorName
    company_id: UUID | None = None


def _invoke(name: CollectorName, company_id: UUID | None) -> None:
    # Each run_* module exposes an async `main(company_id=None)` entrypoint.
    import importlib

    module_map = {
        "ats": "app.jobs.run_ats",
        "rss": "app.jobs.run_rss",
        "github": "app.jobs.run_github",
        "hn": "app.jobs.run_hn",
        "wappalyzer": "app.jobs.run_wappalyzer",
        "scoring": "app.jobs.run_scoring",
        "himalayas": "app.jobs.run_himalayas",
        "jobicy": "app.jobs.run_jobicy",
        "weworkremotely": "app.jobs.run_weworkremotely",
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
    """Hard-delete jobs that have not been seen recently and old intent signals.

    Jobs go stale fast: a posting that disappeared two weeks ago is no longer
    actionable. Signals decay in the scoring engine already, but accumulating
    them indefinitely inflates the table and slows rescoring.
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
