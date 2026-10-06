from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.collectors.ats_collector import ATSCollector
from app.database import SessionLocal
from app.jobs._helpers import configure_job_logging, persist_intent, persist_stack, select_companies

log = logging.getLogger(__name__)


async def main(company_id: UUID | None = None) -> None:
    configure_job_logging()
    db = SessionLocal()
    try:
        companies = select_companies(db, company_id=company_id, require_ats=True)
        log.info("ATS run over %d companies", len(companies))
        async with ATSCollector() as collector:
            for c in companies:
                result = await collector.collect(c)
                intent = persist_intent(db, result["intent"])
                stack = persist_stack(db, result["stack"])
                db.commit()
                log.info("%s: %d intent, %d stack", c.name, intent, stack)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
