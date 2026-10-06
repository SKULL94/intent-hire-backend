from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.database import SessionLocal
from app.jobs._helpers import configure_job_logging
from app.processors.match_engine import refresh_all_matches
from app.processors.scoring_engine import rescore_all, rescore_company

log = logging.getLogger(__name__)


async def main(company_id: UUID | None = None) -> None:
    configure_job_logging()
    db = SessionLocal()
    try:
        if company_id is not None:
            from app.models.company import Company

            company = db.get(Company, company_id)
            if company:
                rescore_company(db, company)
                db.commit()
                log.info("Rescored %s", company.name)
        else:
            count = rescore_all(db)
            log.info("Rescored %d companies", count)
    finally:
        db.close()

    written = refresh_all_matches()
    log.info("Refreshed %d matches", written)


if __name__ == "__main__":
    asyncio.run(main())
