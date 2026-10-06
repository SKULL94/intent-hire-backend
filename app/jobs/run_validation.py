"""Weekly validation snapshot: top-20 ranked companies for later human labeling."""
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from sqlalchemy import select

from app.database import SessionLocal
from app.jobs._helpers import configure_job_logging
from app.models.company_score import CompanyScore
from app.models.validation_snapshot import ValidationSnapshot

log = logging.getLogger(__name__)

TOP_N = 20


async def main(company_id: UUID | None = None) -> None:
    configure_job_logging()
    db = SessionLocal()
    try:
        stmt = (
            select(CompanyScore)
            .order_by(CompanyScore.intent_score.desc())
            .limit(TOP_N)
        )
        rows = list(db.execute(stmt).scalars())
        predictions = [
            {"company_id": str(s.company_id), "score": s.intent_score, "rank": i + 1}
            for i, s in enumerate(rows)
        ]
        snapshot = ValidationSnapshot(top_n=TOP_N, predictions=predictions)
        db.add(snapshot)
        db.commit()
        log.info("Snapshot %s captured %d predictions", snapshot.id, len(predictions))
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
