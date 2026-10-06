"""Guess which ATS a company's careers page uses by probing public endpoints.

Usage: python -m scripts.discover_ats <slug>
       python -m scripts.discover_ats --url https://example.com/careers
"""
from __future__ import annotations

import asyncio
import sys

import httpx

PROBES: list[tuple[str, str]] = [
    ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"),
    ("lever", "https://api.lever.co/v0/postings/{slug}?mode=json"),
    ("ashby", "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"),
    ("workable", "https://apply.workable.com/api/v3/accounts/{slug}/jobs"),
    ("smartrecruiters", "https://api.smartrecruiters.com/v1/companies/{slug}/postings"),
]


async def probe(slug: str) -> None:
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        for ats, url_template in PROBES:
            url = url_template.format(slug=slug)
            try:
                resp = await client.get(url)
            except httpx.HTTPError as exc:
                print(f"  {ats:17s} ERROR  {exc}")
                continue
            status = resp.status_code
            tag = "HIT" if status == 200 else "miss"
            print(f"  {ats:17s} {status} {tag}  {url}")


async def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python -m scripts.discover_ats <slug>")
        sys.exit(1)
    slug = sys.argv[1]
    print(f"Probing ATS boards for slug={slug}")
    await probe(slug)


if __name__ == "__main__":
    asyncio.run(main())
