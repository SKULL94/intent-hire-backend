"""Guess which ATS a company's careers page uses by probing public job boards.

    # probe one slug against every ATS
    python -m scripts.discover_ats razorpay

    # probe every company still marked ats_type='other', print a report
    python -m scripts.discover_ats --batch

    # same, but write confirmed hits back to the companies table
    python -m scripts.discover_ats --batch --apply

A 200 response is *not* on its own a hit: SmartRecruiters answers 200 with
`totalFound: 0` for slugs that do not exist, so matching on status alone maps
every company to SmartRecruiters. A hit requires at least one live posting.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

import httpx
from sqlalchemy import select

from app.database import SessionLocal
from app.models.company import Company

log = logging.getLogger(__name__)

PROBES: list[tuple[str, str]] = [
    ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"),
    ("lever", "https://api.lever.co/v0/postings/{slug}?mode=json"),
    ("ashby", "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"),
    ("workable", "https://apply.workable.com/api/v3/accounts/{slug}/jobs"),
    ("smartrecruiters", "https://api.smartrecruiters.com/v1/companies/{slug}/postings"),
]

# Probe politely — these are other people's APIs and we have no agreement with them.
CONCURRENCY = 4


def job_count(ats: str, payload: Any) -> int:
    """Number of live postings in an ATS board response, or -1 if unparseable."""
    try:
        if ats == "lever":
            return len(payload) if isinstance(payload, list) else -1
        if ats == "smartrecruiters":
            return int(payload.get("totalFound", 0))
        if ats in ("greenhouse", "ashby", "workable"):
            jobs = payload.get("jobs")
            return len(jobs) if isinstance(jobs, list) else -1
    except (AttributeError, TypeError, ValueError):
        return -1
    return -1


def candidate_slugs(company: Company) -> list[str]:
    """Plausible board slugs for a company, most likely first.

    Boards are usually named after the company or its domain, so we try the
    obvious spellings rather than guessing blindly.
    """
    out: list[str] = []
    name = (company.name or "").strip().lower()
    if name:
        collapsed = "".join(ch for ch in name if ch.isalnum())
        hyphenated = "-".join(name.split())
        out += [collapsed, hyphenated]
    if company.domain:
        out.append(company.domain.split(".")[0].lower())
    if company.github_org:
        out.append(company.github_org.lower())

    seen: set[str] = set()
    return [s for s in out if s and not (s in seen or seen.add(s))]


async def probe_slug(client: httpx.AsyncClient, slug: str) -> list[tuple[str, int]]:
    """Return [(ats, job_count)] for every ATS that has live postings for `slug`."""
    hits: list[tuple[str, int]] = []
    for ats, template in PROBES:
        try:
            resp = await client.get(template.format(slug=slug))
        except httpx.HTTPError as exc:
            log.debug("%s/%s probe failed: %s", ats, slug, exc)
            continue
        if resp.status_code != 200:
            continue
        try:
            payload = resp.json()
        except ValueError:
            continue
        count = job_count(ats, payload)
        if count > 0:
            hits.append((ats, count))
    return hits


async def discover(client: httpx.AsyncClient, company: Company) -> tuple[str, str, int] | None:
    """First (ats_type, ats_slug, job_count) that yields live postings."""
    for slug in candidate_slugs(company):
        hits = await probe_slug(client, slug)
        if hits:
            # Prefer the board advertising the most roles.
            ats, count = max(hits, key=lambda h: h[1])
            return ats, slug, count
    return None


async def run_batch(apply: bool) -> None:
    db = SessionLocal()
    try:
        companies = list(
            db.execute(
                select(Company)
                .where(Company.is_active.is_(True))
                .where((Company.ats_type == "other") | (Company.ats_type.is_(None)))
                .order_by(Company.name)
            ).scalars()
        )
        print(f"Probing {len(companies)} companies with no known ATS\n")

        sem = asyncio.Semaphore(CONCURRENCY)
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "HireSignal/1.0 (hiring-intent-research)"},
        ) as client:

            async def one(c: Company) -> tuple[Company, tuple[str, str, int] | None]:
                async with sem:
                    return c, await discover(client, c)

            results = await asyncio.gather(*(one(c) for c in companies))

        found = [(c, r) for c, r in results if r]
        for c, r in results:
            if r:
                ats, slug, count = r
                print(f"  HIT   {c.name:18} -> {ats:15} slug={slug:20} {count} open roles")
            else:
                tried = ",".join(candidate_slugs(c))
                print(f"  miss  {c.name:18}    tried: {tried}")

        print(f"\n{len(found)}/{len(companies)} resolved to a supported ATS")

        if apply and found:
            for c, r in found:
                ats, slug, _ = r
                c.ats_type, c.ats_slug = ats, slug
            db.commit()
            print(f"Updated {len(found)} company rows")
        elif found:
            print("Re-run with --apply to write these to the database")
    finally:
        db.close()


async def run_single(slug: str) -> None:
    print(f"Probing ATS boards for slug={slug}")
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        for ats, template in PROBES:
            url = template.format(slug=slug)
            try:
                resp = await client.get(url)
            except httpx.HTTPError as exc:
                print(f"  {ats:17s} ERROR  {exc}")
                continue
            count = -1
            if resp.status_code == 200:
                try:
                    count = job_count(ats, resp.json())
                except ValueError:
                    count = -1
            tag = f"HIT ({count} roles)" if count > 0 else "miss"
            print(f"  {ats:17s} {resp.status_code} {tag:18s} {url}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slug", nargs="?", help="probe a single slug")
    parser.add_argument("--batch", action="store_true", help="probe all companies lacking an ATS")
    parser.add_argument("--apply", action="store_true", help="with --batch, persist confirmed hits")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.batch:
        asyncio.run(run_batch(apply=args.apply))
    elif args.slug:
        asyncio.run(run_single(args.slug))
    else:
        parser.error("pass a slug or --batch")


if __name__ == "__main__":
    main()
