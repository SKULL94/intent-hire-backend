"""Find a recruiter contact email for a company domain.

Two strategies, tried in order:

1.  Scan stored job description text for email patterns.  Some companies
    (especially small ones that post via their own ATS) include a contact
    address in the posting body.  This is free and instant.

2.  Query Hunter.io's domain-search API.  Hunter crawls the public web and
    maintains a verified index of business email addresses keyed on domain.
    We filter for engineering/tech department addresses because a sales or
    finance contact is useless to a developer sending a cold email.  Requires
    HUNTER_API_KEY; skipped silently if the key is absent.

Neither strategy is guaranteed to produce a result.  Callers receive either a
string email address or None.
"""
from __future__ import annotations

import logging
import re

import httpx

log = logging.getLogger(__name__)

HUNTER_DOMAIN_SEARCH = "https://api.hunter.io/v2/domain-search"

# Engineering/product departments we prefer over generic ones.
_PREFERRED_DEPARTMENTS = frozenset({
    "engineering",
    "technology",
    "product",
    "it",
    "r&d",
    "research",
    "development",
})

# Addresses we never want to surface as a recruiter contact.
_SKIP_PREFIXES = re.compile(
    r"^(noreply|no-reply|donotreply|do-not-reply|bounce|mailer|"
    r"notifications?|alerts?|unsubscribe|support|info|hello|"
    r"contact|admin|abuse|security)@",
    re.I,
)

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)


def extract_from_text(text: str | None) -> str | None:
    """Return the first human-looking email address in `text`, or None."""
    if not text:
        return None
    for m in _EMAIL_RE.finditer(text):
        email = m.group(0)
        if not _SKIP_PREFIXES.match(email):
            return email.lower()
    return None


async def find_via_hunter(domain: str, api_key: str) -> tuple[str | None, str | None]:
    """Return (email, first_name) of the best engineering contact, or (None, None).

    Filters for engineering/tech department first, falls back to any
    high-confidence address.  Returns the contact's first name so the cold
    email can address them by name rather than "Hiring Team".
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                HUNTER_DOMAIN_SEARCH,
                params={"domain": domain, "api_key": api_key, "limit": 20},
            )
    except httpx.HTTPError:
        log.warning("Hunter.io request failed for domain %s", domain)
        return None, None

    if resp.status_code == 401:
        log.error("Hunter.io API key rejected")
        return None, None
    if resp.status_code == 429:
        log.warning("Hunter.io rate-limit hit for domain %s", domain)
        return None, None
    if resp.status_code != 200:
        log.warning("Hunter.io returned %s for domain %s", resp.status_code, domain)
        return None, None

    try:
        emails: list[dict] = resp.json().get("data", {}).get("emails") or []
    except ValueError:
        return None, None

    if not emails:
        return None, None

    # Score each address: prefer engineering department, then confidence.
    def _score(e: dict) -> tuple[int, int]:
        dept = (e.get("department") or "").lower()
        confidence = int(e.get("confidence") or 0)
        return (1 if dept in _PREFERRED_DEPARTMENTS else 0, confidence)

    best = max(emails, key=_score)
    return best.get("value"), best.get("first_name")
