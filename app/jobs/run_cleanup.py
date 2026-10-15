"""Clean the company registry: drop noise, fix names, re-derive evidence.

    python -m app.jobs.run_cleanup --dry-run    # report, change nothing
    python -m app.jobs.run_cleanup              # apply

The collectors now reject this noise on the way in. This job removes what they
already let through, in four passes:

1.  **Staffing firms and entity codes.** A recruitment agency has no Flutter
    stack of its own and never names the client, so it cannot answer "which
    companies hire Flutter". Internal site codes ("ADCI HYD 20 SEZ") are not
    names anyone can act on.

2.  **Name-collision evidence.** Any company whose own name contains a
    technology word tagged itself through its job descriptions. Flutter
    International PLC — a gambling group — produced 16 "Flutter postings" this
    way. Technologies are re-derived with the company name censored.

3.  **Body-only Flutter evidence.** A description that merely mentions Flutter
    is not evidence the company builds in it. Only title-grade matches, GitHub
    Dart ownership, and parsed manifests survive.

4.  **Unsupported companies.** Whatever is left with no evidence at all and no
    postings is dead weight.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.collectors.company_resolver import is_aggregator
from app.database import SessionLocal
from app.jobs._helpers import configure_job_logging
from app.models.company import Company
from app.models.intent_signal import IntentSignal
from app.models.job import Job
from app.models.stack_signal import StackSignal
from app.utils.company_name import clean_display_name, is_entity_code, is_staffing_firm
from app.utils.job_parser import (
    INDIA_REACHABLE_LOCATIONS,
    TITLE_CONFIDENCE,
    detect_technologies,
)

log = logging.getLogger(__name__)

# Stack evidence we trust without a title match.
TRUSTED_SOURCE_TYPES = frozenset({"github", "apk", "pubdev"})

# Evidence written by collectors that no longer exist.
#
# `github_dart_org` measured 100% precision but contributed 0 companies to the
# answer — a GitHub org with no India-or-remote posting cannot pass the
# location filter, so its evidence could never surface. `github` and `blog`
# went with the GitHub scraper and the RSS collector. Keeping any of them
# inflates the registry with companies the product can never show.
RETIRED_SOURCE_TYPES = frozenset({"github_dart_org", "github", "blog"})

# Signal types no longer produced by any collector. Adzuna writes `ats_job`;
# everything else came from RSS (funding/news) or the GitHub scraper.
RETIRED_SIGNAL_TYPES = frozenset({"funding", "news", "github_activity"})

# The only job feed left. A posting from any other source is residue from a
# deleted collector and cannot be refreshed, so it can only go stale.
LIVE_JOB_SOURCES = frozenset({"adzuna"})

FLUTTER_KEYS = ("flutter", "dart")


def _conf(d: dict | None, key: str) -> float:
    try:
        return float((d or {}).get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _is_title_grade(techs: dict | None) -> bool:
    return any(_conf(techs, k) >= TITLE_CONFIDENCE for k in FLUTTER_KEYS)


def _has_flutter(techs: dict | None) -> bool:
    return any(k in (techs or {}) for k in FLUTTER_KEYS)


async def main(dry_run: bool = False, company_id=None) -> None:
    configure_job_logging()
    db = SessionLocal()
    try:
        companies = list(db.execute(select(Company)).scalars())
        log.info("Starting with %d companies", len(companies))

        # ---- pass 0: anything written by a collector that is gone ----------
        retired_stack = list(
            db.execute(
                select(StackSignal).where(
                    StackSignal.source_type.in_(RETIRED_SOURCE_TYPES)
                )
            ).scalars()
        )
        retired_intent = list(
            db.execute(
                select(IntentSignal).where(
                    IntentSignal.signal_type.in_(RETIRED_SIGNAL_TYPES)
                )
            ).scalars()
        )
        retired_jobs = list(
            db.execute(
                select(Job).where(Job.source.not_in(LIVE_JOB_SOURCES))
            ).scalars()
        )
        log.info(
            "Pass 0: %d stack, %d intent, %d postings from retired collectors",
            len(retired_stack),
            len(retired_intent),
            len(retired_jobs),
        )
        if not dry_run:
            for row in (*retired_stack, *retired_intent, *retired_jobs):
                db.delete(row)
            db.flush()

        # ---- pass 1: staffing firms, entity codes, unusable names ----------
        drop: list[Company] = []
        for c in companies:
            if is_staffing_firm(c.name):
                drop.append(c)
                log.info("  staffing    %s", c.name)
            elif is_aggregator(c.name):
                drop.append(c)
                log.info("  aggregator  %s", c.name)
            elif is_entity_code(c.name):
                drop.append(c)
                log.info("  entity code %s", c.name)
            elif not clean_display_name(c.name):
                drop.append(c)
                log.info("  unusable    %r", c.name)
        log.info("Pass 1: %d companies to remove", len(drop))

        # ---- pass 2: re-derive job technologies with the name censored -----
        rewritten = 0
        dropped_ids = {c.id for c in drop}
        jobs = list(
            db.execute(
                select(Job, Company.name)
                .join(Company, Company.id == Job.company_id)
                .where(Job.company_id.not_in(dropped_ids) if dropped_ids else True)
            ).all()
        )
        for job, owner_name in jobs:
            fresh = detect_technologies(
                job.title, job.description, company_name=owner_name
            )
            if fresh != (job.technologies or {}):
                if not dry_run:
                    job.technologies = fresh
                rewritten += 1
        log.info("Pass 2: %d postings re-derived with the company name censored", rewritten)

        # ---- pass 3: drop stack evidence that is not title-grade -----------
        stack_rows = list(db.execute(select(StackSignal)).scalars())
        weak: list[StackSignal] = []
        for s in stack_rows:
            if s.source_type in TRUSTED_SOURCE_TYPES:
                continue
            if not _has_flutter(s.technologies):
                continue
            if not _is_title_grade(s.technologies):
                weak.append(s)
        log.info(
            "Pass 3: %d of %d stack rows carry body-only Flutter evidence",
            len(weak),
            len(stack_rows),
        )

        if dry_run:
            log.info("Dry run - nothing written. Current state:")
            _report(db)
            db.rollback()
            return

        for s in weak:
            db.delete(s)
        for c in drop:
            db.delete(c)
        db.flush()

        # ---- pass 4: companies left with no evidence and no postings -------
        supported = set(
            db.execute(select(StackSignal.company_id).distinct()).scalars()
        ) | set(db.execute(select(IntentSignal.company_id).distinct()).scalars())
        with_jobs = set(db.execute(select(Job.company_id).distinct()).scalars())
        orphans = list(
            db.execute(
                select(Company).where(
                    Company.id.not_in(supported | with_jobs | {None})
                )
            ).scalars()
        )
        for c in orphans:
            db.delete(c)
        log.info("Pass 4: %d companies had no evidence and no postings", len(orphans))

        # ---- pass 5: tidy display names ------------------------------------
        renamed = 0
        for c in db.execute(select(Company)).scalars():
            cleaned = clean_display_name(c.name)
            if cleaned and cleaned != c.name:
                log.info("  rename %r -> %r", c.name, cleaned)
                c.name = cleaned
                renamed += 1
        log.info("Pass 5: %d names tidied", renamed)

        db.commit()
        log.info("Done. After cleaning:")
        _report(db)
    finally:
        db.close()


def _report(db: Session) -> None:
    """Print the answer to the product's one question, post-clean."""
    conditions = [StackSignal.technologies.op("?")(k) for k in FLUTTER_KEYS]
    flutter = set(
        db.execute(
            select(StackSignal.company_id).where(or_(*conditions)).distinct()
        ).scalars()
    )
    reachable = set(
        db.execute(
            select(Job.company_id)
            .where(
                or_(
                    Job.is_remote.is_(True),
                    Job.location_normalized.in_(INDIA_REACHABLE_LOCATIONS),
                )
            )
            .distinct()
        ).scalars()
    )
    ncr = set(
        db.execute(
            select(Job.company_id)
            .where(Job.location_normalized == "delhi_ncr")
            .distinct()
        ).scalars()
    )
    total = db.execute(select(func.count()).select_from(Company)).scalar()
    log.info("  companies tracked:            %d", total)
    log.info("  with Flutter evidence:        %d", len(flutter))
    log.info("  NCR-or-remote reachable:      %d", len(reachable))
    log.info("  BOTH (the answer):            %d", len(flutter & reachable))
    log.info("    with a Delhi NCR role:      %d", len(flutter & ncr))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
