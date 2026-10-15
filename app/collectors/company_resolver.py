"""Turn a company *name* seen in the wild into a tracked company row.

Collectors discover companies in text — a funding headline, a job posting — and
historically had to drop anything they did not already know. That made the
tracked universe a hardcoded list, and meant the richest discovery events (a
company announcing a raise) were thrown away precisely because the company was
new.

This resolves a name against what we already track, and creates it when it is
genuinely new.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.utils.company_name import clean_display_name, is_entity_code, is_staffing_firm

log = logging.getLogger(__name__)

# Legal suffixes and decorations that differ between a headline and our row:
# "Zepto" vs "Zepto Pvt Ltd" vs "Zepto (Kiranakart Technologies)".
_SUFFIXES = re.compile(
    r"\b(pvt\.?|private|ltd\.?|limited|llp|inc\.?|incorporated|corp\.?|"
    r"corporation|co\.?|company|gmbh|bv|plc|technologies|technology|labs|"
    r"software|solutions|systems|group|holdings)\b",
    re.I,
)
_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")

# Names too generic to key on — matching these would merge unrelated companies.
_TOO_GENERIC = {"the", "app", "ai", "tech", "startup", "india", "group", "team", ""}

def normalize_name(name: str) -> str:
    """Comparison key for a company name. Not for display."""
    s = _PUNCT.sub(" ", (name or "").lower())
    s = _SUFFIXES.sub(" ", s)
    return _WS.sub(" ", s).strip()


# Aggregators, reposters and staffing marketplaces. These are indistinguishable
# from an employer on the way in — they run a real Lever/Greenhouse board, so a
# slug probe succeeds — but every posting on it is another company's role,
# republished. Tracking one pollutes the whole pipeline: Jobgether alone
# accounted for 3,934 of 8,191 job rows, none of them Flutter, which skewed
# every per-source yield number and made its reposts compete with first-party
# postings in matching.
#
# Names are given in display spelling and keyed through `normalize_name`.
_AGGREGATORS: frozenset[str] = frozenset(
    normalize_name(n)
    for n in (
        "Jobgether",
        "Y Combinator",
        "Work at a Startup",
        "Turing",
        "Andela",
        "Toptal",
        "Lemon.io",
        "Crossover",
        "Arc.dev",
        "Gun.io",
        "Upwork",
        "Fiverr",
        "Freelancer",
        "Hirist",
        "Instahyre",
        "Cutshort",
        "Naukri",
        "Foundit",
        "Monster",
        "Indeed",
        "LinkedIn",
        "Glassdoor",
        "ZipRecruiter",
        "Wellfound",
        "AngelList",
        "RemoteOK",
        "We Work Remotely",
    )
)


def is_aggregator(name: str) -> bool:
    """True for job boards and reposters that must never be tracked as employers."""
    return normalize_name(name) in _AGGREGATORS


def find_existing(db: Session, name: str, domain: str | None = None) -> Company | None:
    if domain:
        hit = db.execute(
            select(Company).where(func.lower(Company.domain) == domain.lower())
        ).scalar_one_or_none()
        if hit:
            return hit

    key = normalize_name(name)
    if not key or key in _TOO_GENERIC:
        return None

    # Normalization is Python-side, so compare in Python. The company table is
    # small (hundreds), and this runs a handful of times per feed entry.
    for candidate in db.execute(select(Company)).scalars():
        if normalize_name(candidate.name) == key:
            return candidate
    return None


def resolve_or_create(
    db: Session,
    name: str,
    *,
    domain: str | None = None,
) -> Company | None:
    """Existing company for `name`, or a newly created one.

    Returns None when the name is unusable (empty, too generic to key on, or an
    aggregator). The caller is expected to commit.
    """
    raw = (name or "").strip()
    if is_staffing_firm(raw):
        log.info("Skipping staffing firm %r — posts clients' roles unnamed", raw)
        return None
    if is_entity_code(raw):
        log.info("Skipping internal entity code %r", raw)
        return None

    name = clean_display_name(raw) or ""
    key = normalize_name(name)
    if not key or key in _TOO_GENERIC:
        log.debug("Skipping unusable company name %r", raw)
        return None
    if key in _AGGREGATORS:
        log.info("Skipping aggregator %r — reposts other companies' roles", name)
        return None

    existing = find_existing(db, name, domain)
    if existing:
        return existing

    company = Company(name=name, domain=domain, is_active=True)
    db.add(company)
    db.flush()
    log.info("Created company %r", name)
    return company
