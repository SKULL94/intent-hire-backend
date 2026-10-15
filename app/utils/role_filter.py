"""Decide whether a job posting is a technical role worth extracting a stack from.

A job feed is mostly *not* engineering — sampling showed only ~30% of postings
were technical, the rest sales, marketing, recruiting, finance, support, design.

Running stack extraction over all of them is both wasteful and actively harmful:
an Account Executive posting yields the company's *product* vocabulary
("data governance", "data catalog") and a BDR posting yields *sales* tooling
("salesforce", "outreach", "sales navigator"). Those become stack evidence, so a
company gets filed as building in "sales navigator" — and, worse, a posting that
merely *mentions* an app can make a non-Flutter company look like a Flutter one.

We filter on **title** rather than department deliberately. Department labels are
vendor-specific and messy: hundreds of distinct strings, including numeric
prefixes ("8611 Security Analytics"), trailing whitespace, and product-named
engineering teams ("Firefox", "Thunderbird"), with many postings carrying no
department at all. Titles are short, standardized, and always present.
"""
from __future__ import annotations

import re

# Positive signal: the role builds or operates software.
#
# Alternatives that are word *prefixes* carry an explicit `\w*` so the closing
# `\b` still lands on a word boundary — `data scien\b` would never match
# "Data Scientist", because the word continues past "scien".
_TECHNICAL_TITLE = re.compile(
    r"\b("
    r"engineer\w*|developer\w*|programmer\w*|"
    r"sre|devops|architect\w*|"
    r"data scien\w*|machine learning|ai/ml|ml|"
    r"infrastructure|platform|"
    r"backend|back-end|frontend|front-end|full ?stack|"
    r"mobile|android|ios|"
    r"qa|sdet|test automation|"
    r"cloud|database|dba|"
    r"research scien\w*|applied scien\w*"
    r")\b",
    re.I,
)

# Negative signal, applied second. Catches titles that match a technical word
# incidentally — "Sales Engineer" is a quota-carrying sales role, and
# "Engineering Recruiter" hires engineers rather than writing code.
_NON_TECHNICAL_TITLE = re.compile(
    r"\b("
    r"sales|account executive|account manager|"
    r"business development|bdr|sdr|"
    r"marketing|recruit\w*|talent|sourcer|"
    r"people partner|hr|financ\w*|accounting|payroll|"
    r"legal|counsel|compliance manager|"
    r"customer success|community|support specialist|"
    r"office|facilities|executive assistant|chief of staff"
    r")\b",
    re.I,
)


def is_technical_role(title: str | None) -> bool:
    """True when `title` looks like a role whose posting describes a tech stack."""
    if not title:
        return False
    if _NON_TECHNICAL_TITLE.search(title):
        return False
    return bool(_TECHNICAL_TITLE.search(title))
