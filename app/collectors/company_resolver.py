"""Turn a company *name* seen in the wild into a tracked company row.

Collectors discover companies in text — a funding headline, an HN comment — and
historically had to drop anything they did not already know. That made the
tracked universe a hardcoded list, and meant the richest discovery events (a
company announcing a raise) were thrown away precisely because the company was
new.

This resolves a name against what we already track, and creates it when it is
genuinely new, probing for a live ATS board on the way in.
"""
from __future__ import annotations

import logging
import re

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.company import Company

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


def _slug_candidates(name: str, domain: str | None) -> list[str]:
    out: list[str] = []
    key = normalize_name(name)
    if key:
        out += ["".join(key.split()), "-".join(key.split())]
    if domain:
        out.append(domain.split(".")[0].lower())
    seen: set[str] = set()
    return [s for s in out if s and not (s in seen or seen.add(s))]


async def resolve_or_create(
    db: Session,
    client: httpx.AsyncClient,
    name: str,
    *,
    domain: str | None = None,
    probe_ats: bool = True,
) -> Company | None:
    """Existing company for `name`, or a newly created one.

    Returns None only when the name is unusable (empty or too generic to key
    on). The caller is expected to commit.
    """
    name = (name or "").strip()
    key = normalize_name(name)
    if not key or key in _TOO_GENERIC:
        log.debug("Skipping unusable company name %r", name)
        return None

    existing = find_existing(db, name, domain)
    if existing:
        return existing

    ats_type, ats_slug = "other", None
    if probe_ats:
        # Imported here: scripts/ is not a package the app imports at module
        # load time, and only this path needs it.
        from scripts.discover_ats import probe_slug

        for slug in _slug_candidates(name, domain):
            try:
                hits = await probe_slug(client, slug)
            except Exception:  # noqa: BLE001
                log.debug("ATS probe failed for %s/%s", name, slug, exc_info=True)
                continue
            if hits:
                ats_type, ats_slug = max(hits, key=lambda h: h[1])[0], slug
                log.info("Discovered %s -> %s board (slug=%s)", name, ats_type, slug)
                break

    company = Company(
        name=name,
        domain=domain,
        ats_type=ats_type,
        ats_slug=ats_slug,
        # A company discovered from a hiring/funding event has real intent, so
        # unlike a stack-only discovery it belongs in matching immediately.
        is_active=True,
    )
    db.add(company)
    db.flush()
    log.info("Created company %r (ats=%s)", name, ats_type)
    return company
