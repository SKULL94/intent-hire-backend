from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.collectors.weworkremotely_scraper import WeWorkRemotelyCollector
from app.database import SessionLocal
from app.jobs._helpers import (
    configure_job_logging,
    persist_intent,
    persist_jobs,
    persist_stack,
    synthesize_signals_from_jobs,
)
from app.processors.scoring_engine import rescore_all

log = logging.getLogger(__name__)


async def main(company_id: UUID | None = None) -> None:
    configure_job_logging()
    db = SessionLocal()
    try:
        async with WeWorkRemotelyCollector() as collector:
            result = await collector.collect_all(db)
        written, skipped = persist_jobs(db, result["jobs"])
        intent_rows, stack_rows = synthesize_signals_from_jobs(
            result["jobs"], source="weworkremotely"
        )
        persist_intent(db, intent_rows)
        persist_stack(db, stack_rows)
        db.commit()
        log.info(
            "WeWorkRemotely run: %d jobs upserted%s, %d companies signalled",
            written,
            f" ({skipped} skipped)" if skipped else "",
            len(intent_rows),
        )
        if intent_rows:
            rescore_all(db)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
