"""Company names as they arrive from a job feed, and what is wrong with them.

Adzuna publishes whatever the poster typed. Across one run that produced
truncated names ("Aarms Solutions on"), internal entity codes ("ADCI HYD 20
SEZ" — an Amazon India subsidiary), legal boilerplate ("... PRIVATE LIMITED"),
and a long tail of staffing agencies posting on behalf of unnamed clients.

The last group matters most. A staffing agency is the exact thing this product
exists to route around: you cannot tell which employer the role is for, the
agency has no Flutter stack of its own, and contacting them puts you back in
the pile this whole system was built to escape.
"""
from __future__ import annotations

import re

# Staffing agencies, recruitment consultancies and body shops. These post other
# companies' roles without naming the client, so they are never a useful answer
# to "which companies hire Flutter".
_STAFFING = re.compile(
    r"\b("
    r"staffing|recruit\w*|recruitment|placements?|manpower|"
    r"hr\s+(solutions?|services?|consult\w*)|"
    r"talent\s+(acquisition|solutions?|services?|partners?)|"
    r"job\s*(s|board|portal)?\b|hiring\s+(partners?|solutions?)|"
    r"nearshore|offshore\s+staffing|"
    r"consultancy|consultants?|"
    r"workforce|outsourcing|"
    r"rpo|headhunt\w*"
    r")\b",
    re.I,
)

# "Consulting" alone is too broad — Capco, Nihilent and Thoughtworks are real
# employers that build software. Only treat it as staffing when it sits next to
# a recruitment word.
_CONSULTING_STAFFING = re.compile(
    r"\bconsult\w*\b.*\b(hr|staffing|recruit\w*|talent|manpower|placements?)\b"
    r"|\b(hr|staffing|recruit\w*|talent|manpower|placements?)\b.*\bconsult\w*\b",
    re.I,
)

# Internal subsidiary/site codes, not names a person would recognise:
# "ADCI HYD 20 SEZ", "ADCI - Karnataka", "AWS India - BLR 14".
_ENTITY_CODE = re.compile(
    r"^(adci|aws\s+india|amzn|amazon\s+dev\w*\s+cent\w*)\b"
    r"|^[A-Z]{3,5}[\s\-]+[A-Z]{2,4}[\s\-]+\d+"
    r"|\b(sez|stpi)\b\s*$",
    re.I,
)

# Dangling words left by a truncated feed value: "Aarms Solutions on",
# "Something Technologies and".
_DANGLING = re.compile(
    r"\s+(on|in|at|for|and|or|the|of|with|to|a|an|is|are|we|you)\s*$", re.I
)

# Legal decoration. Stripped for display only — never for identity, because
# "Acme Pvt Ltd" and "Acme Inc" can be different companies.
_LEGAL_TAIL = re.compile(
    r"[\s,\.]*\b("
    r"pvt\.?|private|ltd\.?|limited|llp|llc|inc\.?|incorporated|"
    r"corp\.?|corporation|co\.?|plc|gmbh|bv|s\.?a\.?"
    r")\b[\s,\.]*",
    re.I,
)

_WS = re.compile(r"\s+")


def is_staffing_firm(name: str | None) -> bool:
    """True for recruitment agencies and body shops posting clients' roles."""
    if not name:
        return False
    return bool(_STAFFING.search(name) or _CONSULTING_STAFFING.search(name))


def is_entity_code(name: str | None) -> bool:
    """True for internal subsidiary or site codes rather than company names."""
    if not name:
        return False
    return bool(_ENTITY_CODE.search(name.strip()))


def clean_display_name(name: str | None) -> str | None:
    """Tidy a feed-supplied name for display, or None if nothing usable remains.

    Collapses whitespace, drops a trailing dangling word left by truncation,
    strips repeated legal suffixes, and fixes SHOUTED names. Identity is keyed
    on `company_resolver.normalize_name`, not on this, so trimming here is safe.
    """
    if not name:
        return None

    out = _WS.sub(" ", name).strip(" \t\r\n-–—,.|/\\&+")
    if not out:
        return None

    # Truncated feed values: strip one dangling word, repeatedly.
    while True:
        trimmed = _DANGLING.sub("", out)
        if trimmed == out:
            break
        out = trimmed.strip()

    # Collapse legal decoration to a single trailing form. "Zino & Co." must
    # not become "Zino &", so strip a trailing connector afterwards too.
    without_legal = _WS.sub(" ", _LEGAL_TAIL.sub(" ", out)).strip(" ,.&+-")
    if without_legal and len(without_legal) >= 3:
        out = without_legal

    # "MAXGEN TECHNOLOGIES PRIVATE LIMITED" -> "Maxgen Technologies".
    # Leave genuine acronyms (CGI, HDFC, InMobi) alone: only reshape when the
    # name is all-caps *and* multi-word, which is feed shouting, not a brand.
    if out.isupper() and len(out.split()) > 1:
        out = out.title()

    if len(out) < 2:
        return None
    return out
