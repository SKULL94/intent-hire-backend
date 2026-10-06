from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.collectors.hn_whos_hiring import HNCollector
from app.database import SessionLocal
from app.jobs._helpers import configure_job_logging, persist_intent, persist_stack

log = logging.getLogger(__name__)


async def main(company_id: UUID | None = None) -> None:
    configure_job_logging()
    db = SessionLocal()
    try:
        async with HNCollector() as collector:
            result = await collector.collect_all(db)
            intent = persist_intent(db, result["intent"])
            stack = persist_stack(db, result["stack"])
            db.commit()
            log.info("HN run: %d intent, %d stack", intent, stack)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
