"""Harvest Flutter/Dart postings from RemoteOK.

    python -m app.jobs.run_remoteok
"""
from __future__ import annotations

import asyncio
import logging

from app.collectors.remoteok_scraper import RemoteOKCollector
from app.database import SessionLocal
from app.jobs._helpers import configure_job_logging, persist_jobs

log = logging.getLogger(__name__)


async def main() -> None:
    configure_job_logging()
    db = SessionLocal()
    try:
        async with RemoteOKCollector() as collector:
            result = await collector.collect_all(db)
        written, skipped = persist_jobs(db, result["jobs"])
        db.commit()
        log.info(
            "RemoteOK run: %d jobs upserted%s",
            written,
            f" ({skipped} skipped)" if skipped else "",
        )
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
