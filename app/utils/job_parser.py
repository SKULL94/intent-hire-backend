"""Turn a raw job posting into the three things we filter on.

Deliberately deterministic regex rather than an LLM call. For an exact-token
question like "does this posting say Flutter", a keyword match is cheaper,
reproducible, and more precise than a model that is allowed to infer. It is
also the reason there is no LLM anywhere in this service.
"""
from __future__ import annotations

import re

# ─── technologies ────────────────────────────────────────────────────────────
# Word-boundary patterns so "dart" does not match "dartboard" and "go" does not
# match every third word. Ambiguous one- and two-letter names are only matched
# in their unambiguous spelling ("golang", not "go").
TECH_PATTERNS: dict[str, str] = {
    "flutter": r"flutter",
    "dart": r"dart(?:lang)?",
    "kotlin": r"kotlin",
    "swift": r"swift(?:ui)?",
    "react-native": r"react[\s-]?native",
    "android": r"android",
    "ios": r"ios",
    "react": r"react(?!\s*native)(?:\.?js)?",
    "angular": r"angular(?:js)?",
    "vue": r"vue(?:\.?js)?",
    "typescript": r"typescript",
    "javascript": r"javascript",
    "python": r"python",
    "django": r"django",
    "fastapi": r"fastapi",
    "flask": r"flask",
    "java": r"java(?!script)",
    "golang": r"golang|\bgo\s+(?:lang|developer|engineer)",
    "rust": r"rust",
    "ruby": r"ruby(?:\s+on\s+rails)?",
    "php": r"php",
    "laravel": r"laravel",
    "nodejs": r"node(?:\.?js)?",
    "nextjs": r"next\.?js",
    "postgresql": r"postgres(?:ql)?",
    "mysql": r"mysql",
    "mongodb": r"mongo(?:db)?",
    "redis": r"redis",
    "firebase": r"firebase",
    "supabase": r"supabase",
    "graphql": r"graphql",
    "aws": r"\baws\b|amazon web services",
    "gcp": r"\bgcp\b|google cloud",
    "azure": r"\bazure\b",
    "docker": r"docker",
    "kubernetes": r"kubernetes|\bk8s\b",
    "terraform": r"terraform",
}

_COMPILED: dict[str, re.Pattern[str]] = {
    tech: re.compile(rf"(?<![\w-]){pattern}(?![\w-])", re.I)
    for tech, pattern in TECH_PATTERNS.items()
}

# A technology in the title is what the role *is*; in the body it may be one
# line of a long "nice to have" list.
TITLE_CONFIDENCE = 0.95
BODY_CONFIDENCE = 0.7


def detect_technologies(
    title: str | None,
    description: str | None,
    *,
    company_name: str | None = None,
) -> dict[str, float]:
    """Technology -> confidence, from the posting's own words.

    `company_name` is removed from both fields before matching. Without that,
    any company whose name collides with a technology tags itself: Flutter
    International PLC (the gambling group) produced 16 "Flutter postings"
    purely because its own name appears in every description it publishes.
    """
    title = _without_company_name(title or "", company_name)
    description = _without_company_name(description or "", company_name)
    out: dict[str, float] = {}
    for tech, pattern in _COMPILED.items():
        if pattern.search(title):
            out[tech] = TITLE_CONFIDENCE
        elif pattern.search(description):
            out[tech] = BODY_CONFIDENCE
    return out


def _without_company_name(text: str, company_name: str | None) -> str:
    if not company_name or not text:
        return text
    # Drop legal decoration so "Flutter International PLC" also censors a bare
    # "Flutter" and "Flutter Entertainment".
    bare = re.sub(
        r"\b(pvt\.?|private|ltd\.?|limited|llp|inc\.?|corp\.?|plc|group|"
        r"technologies|technology|solutions|systems|labs|software|international|"
        r"entertainment|services)\b",
        " ",
        company_name,
        flags=re.I,
    )
    tokens = [t for t in re.split(r"[^\w]+", bare) if len(t) > 2]
    if not tokens:
        return text
    return re.sub("|".join(re.escape(t) for t in tokens), " ", text, flags=re.I)


# ─── experience ──────────────────────────────────────────────────────────────
# Ordered: the first pattern that matches wins, so ranges are read before bare
# single numbers and we take the bottom of the range rather than the top.
_YEARS_PATTERNS: list[re.Pattern[str]] = [
    # "3-5 years", "3 to 5 years", "3 - 5 yrs"
    re.compile(r"(\d{1,2})\s*(?:-|–|to)\s*\d{1,2}\s*\+?\s*(?:years?|yrs?)", re.I),
    # "minimum 3 years", "at least 3 years", "3+ years"
    re.compile(r"(?:minimum|min\.?|at least|atleast)\s*(?:of\s*)?(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.I),
    re.compile(r"(\d{1,2})\s*\+\s*(?:years?|yrs?)", re.I),
    # "3 years of experience"
    re.compile(r"(\d{1,2})\s*(?:years?|yrs?)\s+(?:of\s+)?(?:relevant\s+|professional\s+|hands[\s-]on\s+)?experience", re.I),
]

# Above this, the number is almost certainly not a requirement — it is a
# company age ("25 years in business") or a headcount.
_MAX_PLAUSIBLE_YEARS = 15


def parse_min_years(text: str | None) -> int | None:
    """Minimum years of experience the posting asks for, when it says so."""
    if not text:
        return None
    for pattern in _YEARS_PATTERNS:
        for match in pattern.finditer(text):
            try:
                years = int(match.group(1))
            except (ValueError, IndexError):
                continue
            if 0 <= years <= _MAX_PLAUSIBLE_YEARS:
                return years
    return None


# ─── location ────────────────────────────────────────────────────────────────
# Ordered most specific first: "Greater Noida" must be tested before a bare
# city list, and NCR satellite towns must map to delhi_ncr rather than to
# themselves, because that is how people actually search.
_LOCATION_GROUPS: list[tuple[str, str]] = [
    (
        "delhi_ncr",
        r"delhi|new\s*delhi|ncr|noida|greater\s*noida|gurgaon|gurugram|"
        r"ghaziabad|faridabad|dwarka",
    ),
    ("bengaluru", r"bengaluru|bangalore"),
    ("mumbai", r"mumbai|bombay|navi\s*mumbai|thane"),
    ("pune", r"\bpune\b"),
    ("hyderabad", r"hyderabad|secunderabad"),
    ("chennai", r"chennai|madras"),
    ("kolkata", r"kolkata|calcutta"),
    ("ahmedabad", r"ahmedabad|gandhinagar"),
    ("india_other", r"\bindia\b"),
]

_COMPILED_LOCATIONS = [
    (name, re.compile(pattern, re.I)) for name, pattern in _LOCATION_GROUPS
]

# The key `normalize_location` uses for a posting that is remote but names no
# recognizable Indian city.
REMOTE_LOCATION_KEY = "remote"

# Every location key reachable by a candidate based in India — the Indian city
# buckets plus plain "remote".
#
# Consumers MUST filter against this set rather than re-deriving it. The keys
# are city names, so the obvious-looking test `location_normalized LIKE
# '%india%'` matches only `india_other` and silently drops `delhi_ncr`,
# `bengaluru`, `hyderabad` and the rest. A `NULL` key is *not* "unknown" — it
# means the location was read and resolved to somewhere else ("US", "Brazil"),
# so it is correctly excluded.
INDIA_REACHABLE_LOCATIONS: frozenset[str] = frozenset(
    [name for name, _ in _LOCATION_GROUPS] + [REMOTE_LOCATION_KEY]
)

_REMOTE = re.compile(
    r"\bremote\b|work\s*from\s*home|\bwfh\b|fully\s*distributed|anywhere", re.I
)


def normalize_location(raw: str | None) -> tuple[str | None, bool]:
    """`(normalized_key, is_remote)` for a published location string.

    Remote is independent of the key: "Remote, Delhi" is both remote and NCR,
    and a seeker filtering for either should see it.
    """
    if not raw:
        return None, False
    is_remote = bool(_REMOTE.search(raw))
    for name, pattern in _COMPILED_LOCATIONS:
        if pattern.search(raw):
            return name, is_remote
    if is_remote:
        return "remote", True
    return None, False
