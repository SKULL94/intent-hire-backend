from __future__ import annotations

import asyncio
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_service_key
from app.database import get_db
from app.models.intent_signal import IntentSignal

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_service_key)])

CollectorName = Literal["ats", "rss", "github", "hn", "wappalyzer", "scoring"]


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
