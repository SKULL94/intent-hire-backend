"""Harvest Flutter/Dart postings from Arbeitnow.

    python -m app.jobs.run_arbeitnow
"""
from __future__ import annotations

import asyncio
import logging

from app.collectors.arbeitnow_scraper import ArbeitnowCollector
from app.database import SessionLocal
from app.jobs._helpers import configure_job_logging, persist_jobs

log = logging.getLogger(__name__)


async def main() -> None:
    configure_job_logging()
    db = SessionLocal()
    try:
        async with ArbeitnowCollector() as collector:
            result = await collector.collect_all(db)
        written, skipped = persist_jobs(db, result["jobs"])
        db.commit()
        log.info(
            "Arbeitnow run: %d jobs upserted%s",
            written,
            f" ({skipped} skipped)" if skipped else "",
        )
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
