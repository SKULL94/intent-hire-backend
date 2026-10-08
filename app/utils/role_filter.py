"""Decide whether a job posting is a technical role worth extracting a stack from.

A company's job board is mostly *not* engineering. Sampling the 18 boards we
currently track returned 1,769 open roles, of which only ~30% were technical —
the rest were sales, marketing, recruiting, finance, support, and design.

Running stack extraction over all of them is both wasteful and actively harmful:
an Account Executive posting yields the company's *product* vocabulary
("data governance", "data catalog") and a BDR posting yields *sales* tooling
("salesforce", "outreach", "sales navigator"). Those land in
`company_scores.stack_fingerprint` and then drive `tech_fit`, which is 60% of a
match score — so a user who writes Python gets scored against "sales navigator".

We filter on **title** rather than department deliberately. Department labels are
vendor-specific and messy: 347 distinct strings across those same boards,
including numeric prefixes ("8611 Security Analytics"), trailing whitespace, and
product-named engineering teams ("Firefox", "Thunderbird"). 203 postings carried
no department at all. Titles are short, standardized, and always present.
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
