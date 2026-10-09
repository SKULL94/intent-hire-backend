"""Harvest job postings from Adzuna.

    python -m app.jobs.run_adzuna                       # flutter+dart, India
    python -m app.jobs.run_adzuna --what flutter react  # other technologies
    python -m app.jobs.run_adzuna --country gb          # another market
    python -m app.jobs.run_adzuna --nationwide          # skip the city loop

Searching per city as well as nationwide is deliberate: Adzuna's relevance
ordering means a nationwide query for a popular term never pages deep enough to
surface every Delhi NCR role, and NCR is the reason this collector exists.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from app.collectors.adzuna_scraper import AdzunaCollector
from app.database import SessionLocal
from app.jobs._helpers import configure_job_logging, persist_jobs

log = logging.getLogger(__name__)

DEFAULT_QUERIES = ["flutter", "dart"]

# Adzuna matches these against its own location taxonomy, so the spellings
# that its index actually uses matter more than official city names.
NCR_LOCATIONS = ["Delhi", "Noida", "Gurgaon", "Gurugram", "Ghaziabad", "Faridabad"]


async def main(
    queries: list[str] | None = None,
    country: str = "in",
    nationwide_only: bool = False,
) -> None:
    configure_job_logging()
    queries = queries or DEFAULT_QUERIES
    locations: list[str | None] = [None] if nationwide_only else [None, *NCR_LOCATIONS]

    db = SessionLocal()
    try:
        async with AdzunaCollector() as collector:
            result = await collector.collect_all(
                db, queries=queries, country=country, locations=locations
            )
        written, skipped = persist_jobs(db, result["jobs"])
        db.commit()
        log.info(
            "Adzuna run: %d jobs upserted%s", written, f" ({skipped} skipped)" if skipped else ""
        )
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--what", nargs="+", default=None, help="search terms")
    parser.add_argument("--country", default="in", help="Adzuna country code")
    parser.add_argument("--nationwide", action="store_true", help="skip per-city queries")
    args = parser.parse_args()
    asyncio.run(main(queries=args.what, country=args.country, nationwide_only=args.nationwide))
