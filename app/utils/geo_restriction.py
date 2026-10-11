"""Does a remote job allow an Indian candidate?

Remote boards publish a lot of 'US only' / 'EU only' / 'UK only' postings.
For a candidate based in India those are unreachable, and keeping them in the
funnel means a match page where half the links go to roles the user cannot
apply to. We drop them before resolving a company or persisting a job row.

This is intentionally a keyword filter. False negatives (losing a reachable
job) cost more than false positives (surfacing a job the user has to discard),
so when the phrasing is ambiguous the posting is kept.
"""
from __future__ import annotations

import re

# India-friendly phrasings. Any of these overrides a region-exclusion match in
# the same text ("Remote worldwide, US-based team").
_INCLUDES_INDIA = re.compile(
    r"\b(india|worldwide|anywhere|global\s*remote|"
    r"any\s*(location|country|timezone)|apac|asia(?!n))\b",
    re.I,
)

# Hard eligibility restrictions. These are the phrases that *actually* exclude
# non-US/EU candidates in practice: timezone fences, visa requirements, and the
# explicit "X only" formulations boards use for region tags.
_EXCLUDES_INDIA = re.compile(
    r"\b("
    r"us\s*only|usa\s*only|us-only|usa-only|"
    r"north\s*america\s*only|americas\s*only|"
    r"eu\s*only|europe\s*only|eea\s*only|emea\s*only|"
    r"uk\s*only|united\s*kingdom\s*only|"
    r"canada\s*only|canadian\s*citizens?\s*only|"
    r"us\s*citizens?\s*only|green\s*card|security\s*clearance|"
    r"must\s*(?:be\s*)?(?:located|based|reside|live)\s*in\s*(?:the\s*)?"
    r"(?:us|usa|united\s*states|uk|europe|eu|canada|north\s*america|emea|americas)"
    r")\b",
    re.I,
)


def is_india_allowed(text: str | None) -> bool:
    """True unless `text` carries a geo restriction clearly excluding India."""
    if not text:
        return True
    if _INCLUDES_INDIA.search(text):
        return True
    return not bool(_EXCLUDES_INDIA.search(text))


# Remotive publishes a `candidate_required_location` field with a controlled
# vocabulary. We trust it over the loose regex when it is set. Values seen:
# "", "Worldwide", "Anywhere", "USA", "USA Only", "USA, UK", "Europe",
# "Latin America", "APAC", "India".
_REMOTIVE_HOSTILE_REGIONS = {
    "usa", "us", "united states",
    "canada", "ca",
    "uk", "united kingdom", "gb",
    "europe", "eu", "eea",
    "north america", "americas",
    "australia", "new zealand",
    "latin america", "latam",
}


def remotive_region_allows_india(required_location: str | None) -> bool:
    if not required_location:
        return True
    norm = required_location.strip().lower()
    if (
        "india" in norm
        or "worldwide" in norm
        or "anywhere" in norm
        or "apac" in norm
        or "asia" in norm
    ):
        return True
    # The field is sometimes a comma-separated list ("USA, UK"). Reject only if
    # *every* token is a region India is not in — a mixed list that names any
    # region we do not recognize falls through to permissive.
    tokens = [t.strip().replace(" only", "") for t in re.split(r"[,;/|]", norm) if t.strip()]
    if tokens and all(t in _REMOTIVE_HOSTILE_REGIONS for t in tokens):
        return False
    return True
