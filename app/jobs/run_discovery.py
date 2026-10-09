"""Grow the tracked company universe from evidence instead of a hardcoded list.

    python -m app.jobs.run_discovery                 # discover, probe, persist
    python -m app.jobs.run_discovery --dry-run       # report only
    python -m app.jobs.run_discovery --limit 120     # cap orgs hydrated

Pipeline:
    GitHub Dart repos -> owning organizations -> company domain
        -> probe for a live ATS board (discover_ats)
        -> upsert Company
        -> stack_signal: this company builds in Flutter

A company is created even when no ATS board is found. That is deliberate: the
Flutter stack evidence is real either way, and `ats_type='other'` is exactly how
the existing pipeline records "we know them, we cannot read their jobs". They
still collect GitHub and Wappalyzer signals.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from app.collectors.dart_org_discovery import DartOrgDiscovery
from app.database import SessionLocal
from app.jobs._helpers import configure_job_logging, persist_stack
from app.models.company import Company
from scripts.discover_ats import probe_slug

log = logging.getLogger(__name__)

# Confidence that an org owning public Dart repos builds in Flutter. High, but
# below the 0.95 that a parsed `pubspec.yaml` earns in github_scraper: owning a
# Dart repo is strong evidence, reading the manifest is proof.
DART_ORG_CONFIDENCE = 0.85

ATS_PROBE_CONCURRENCY = 4


def _candidate_slugs(name: str, domain: str, github_org: str) -> list[str]:
    """Plausible job-board slugs, most likely first. Mirrors discover_ats."""
    out: list[str] = []
    collapsed = "".join(ch for ch in name.lower() if ch.isalnum())
    if collapsed:
        out += [collapsed, "-".join(name.lower().split())]
    out.append(domain.split(".")[0].lower())
    out.append(github_org.lower())
    seen: set[str] = set()
    return [s for s in out if s and not (s in seen or seen.add(s))]


async def _resolve_ats(
    client: httpx.AsyncClient, candidate: dict
) -> tuple[str, str, int] | None:
    for slug in _candidate_slugs(
        candidate["name"], candidate["domain"], candidate["github_org"]
    ):
        hits = await probe_slug(client, slug)
        if hits:
            ats, count = max(hits, key=lambda h: h[1])
            return ats, slug, count
    return None


async def main(dry_run: bool = False, limit: int | None = 150) -> None:
    configure_job_logging()

    async with DartOrgDiscovery() as discovery:
        candidates = await discovery.discover(limit=limit)

    if not candidates:
        log.warning("Discovery returned no candidates")
        return

    db = SessionLocal()
    try:
        known_domains = {d for (d,) in db.execute(select(Company.domain)).all() if d}
        known_orgs = {
            o.lower() for (o,) in db.execute(select(Company.github_org)).all() if o
        }
        fresh = [
            c
            for c in candidates
            if c["domain"] not in known_domains
            and c["github_org"].lower() not in known_orgs
        ]
        log.info("%d candidates, %d not already tracked", len(candidates), len(fresh))

        # Probe every fresh candidate for a readable job board.
        semaphore = asyncio.Semaphore(ATS_PROBE_CONCURRENCY)
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "HireSignal/1.0 (hiring-intent-research)"},
        ) as client:

            async def probe(c: dict):
                async with semaphore:
                    return c, await _resolve_ats(client, c)

            probed = await asyncio.gather(*(probe(c) for c in fresh))

        with_board = [(c, r) for c, r in probed if r]
        log.info("%d of %d resolved to a live ATS board", len(with_board), len(probed))

        for c, resolved in probed:
            ats_type, ats_slug = ("other", None)
            roles = 0
            if resolved:
                ats_type, ats_slug, roles = resolved
            marker = "BOARD" if resolved else "  -  "
            log.info(
                "  %s %-26s %-22s %-16s %s",
                marker,
                c["name"][:26],
                c["domain"][:22],
                ats_type,
                f"{roles} roles" if roles else "",
            )

        if dry_run:
            log.info("Dry run - nothing written")
            return

        now = datetime.now(timezone.utc)
        stack_rows: list[dict] = []
        created = 0
        for c, resolved in probed:
            ats_type, ats_slug = ("other", None)
            if resolved:
                ats_type, ats_slug, _ = resolved
            # Only companies with a readable board enter matching.
            #
            # A match score is 0.4*intent + 0.6*tech_fit*100. A discovered org
            # has strong Flutter evidence and no intent signal at all, so for a
            # Flutter developer it would score ~51 on stack fit alone and rank
            # *above* companies that are genuinely hiring. Keeping it inactive
            # preserves the stack evidence without corrupting the ranking; a
            # later source that gives it intent can flip the flag.
            company = Company(
                name=c["name"],
                domain=c["domain"],
                github_org=c["github_org"],
                location=c.get("location"),
                website=f"https://{c['domain']}",
                ats_type=ats_type,
                ats_slug=ats_slug,
                is_active=bool(resolved),
            )
            db.add(company)
            db.flush()  # assign company.id for the stack row below
            created += 1
            stack_rows.append(
                {
                    "company_id": company.id,
                    "source_type": "github_dart_org",
                    "source_url": f"https://github.com/{c['github_org']}",
                    "technologies": {
                        "flutter": DART_ORG_CONFIDENCE,
                        "dart": DART_ORG_CONFIDENCE,
                    },
                    "raw_evidence": f"org owns public Dart repos (top repo {c['stars']} stars)",
                    "detected_at": now,
                }
            )

        persisted = persist_stack(db, stack_rows)
        db.commit()
        log.info(
            "Created %d companies (%d with a readable board), %d Flutter stack signals",
            created,
            len(with_board),
            persisted,
        )
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    parser.add_argument("--limit", type=int, default=150, help="max orgs to hydrate")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run, limit=args.limit))
