"""Seed companies with VERIFIED ATS slugs.

Each row below has had its ATS slug confirmed to return HTTP 200 with real job
listings as of initial setup. If you're adding a new company, probe first:

    python -m scripts.discover_ats <slug>

Idempotent on domain: existing rows are left alone.
Usage: python -m scripts.seed_companies
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.database import SessionLocal
from app.models.company import Company

log = logging.getLogger(__name__)

# ─── Verified Indian tech companies (ATS slugs confirmed live) ───────────────
INDIAN_VERIFIED: list[dict] = [
    {"name": "CRED", "domain": "cred.club", "ats_type": "lever", "ats_slug": "cred",
     "careers_url": "https://cred.club/careers", "github_org": None},
    {"name": "Fi.Money", "domain": "fi.money", "ats_type": "lever", "ats_slug": "fi",
     "careers_url": "https://fi.money/careers", "github_org": None},
    {"name": "Druva", "domain": "druva.com", "ats_type": "greenhouse", "ats_slug": "druva",
     "careers_url": "https://www.druva.com/company/careers", "github_org": "druvaio"},
]

# ─── Indian companies whose ATS slug still needs discovery ───────────────────
# These rows are inserted with ats_type="other" so they're skipped by the ATS
# collector but still get GitHub, Wappalyzer, RSS, and HN signals. Once you
# confirm a slug via `discover_ats`, update the row in the DB (or edit this
# file) and move it into INDIAN_VERIFIED.
INDIAN_UNVERIFIED: list[dict] = [
    {"name": "Razorpay", "domain": "razorpay.com", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://razorpay.com/jobs/", "github_org": "razorpay"},
    {"name": "Swiggy", "domain": "swiggy.com", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://careers.swiggy.com/", "github_org": "swiggy"},
    {"name": "Zomato", "domain": "zomato.com", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://www.zomato.com/careers", "github_org": "zomato"},
    {"name": "PhonePe", "domain": "phonepe.com", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://www.phonepe.com/careers/", "github_org": "PhonePe"},
    {"name": "Groww", "domain": "groww.in", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://groww.in/careers", "github_org": "Groww"},
    {"name": "Meesho", "domain": "meesho.com", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://www.meesho.io/careers", "github_org": "Meesho"},
    {"name": "Zerodha", "domain": "zerodha.com", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://zerodha.com/careers/", "github_org": "zerodha"},
    {"name": "Freshworks", "domain": "freshworks.com", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://www.freshworks.com/company/careers/", "github_org": "freshworks"},
    {"name": "Postman", "domain": "postman.com", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://www.postman.com/company/careers/", "github_org": "postmanlabs"},
    {"name": "Chargebee", "domain": "chargebee.com", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://www.chargebee.com/careers/", "github_org": "chargebee"},
    {"name": "Flipkart", "domain": "flipkart.com", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://www.flipkartcareers.com/", "github_org": "flipkart-incubator"},
    {"name": "Myntra", "domain": "myntra.com", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://careers.myntra.com/", "github_org": "myntra"},
    {"name": "ShareChat", "domain": "sharechat.com", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://sharechat.com/careers", "github_org": "sharechat"},
    {"name": "Urban Company", "domain": "urbancompany.com", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://www.urbancompany.com/careers", "github_org": "UrbanClap"},
    {"name": "unacademy", "domain": "unacademy.com", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://unacademy.com/careers", "github_org": "unacademy"},
    {"name": "Khatabook", "domain": "khatabook.com", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://khatabook.com/careers", "github_org": "khatabook"},
    {"name": "Zepto", "domain": "zeptonow.com", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://www.zeptonow.com/careers", "github_org": None},
    {"name": "Hasura", "domain": "hasura.io", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://hasura.io/careers/", "github_org": "hasura"},
    {"name": "BrowserStack", "domain": "browserstack.com", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://www.browserstack.com/careers", "github_org": "browserstack"},
    {"name": "Mindtickle", "domain": "mindtickle.com", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://www.mindtickle.com/careers/", "github_org": "mindtickle"},
    {"name": "Atlan", "domain": "atlan.com", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://atlan.com/careers/", "github_org": "atlanhq"},
    {"name": "Setu", "domain": "setu.co", "ats_type": "other", "ats_slug": None,
     "careers_url": "https://setu.co/careers", "github_org": "SetuHQ"},
]

# ─── US tech companies with verified Greenhouse slugs ────────────────────────
# Useful for Phase 1 testing — these guarantee the ATS pipeline sees real jobs
# while you confirm Indian company slugs.
US_VERIFIED_PHASE1_TESTING: list[dict] = [
    {"name": "Stripe", "domain": "stripe.com", "ats_type": "greenhouse", "ats_slug": "stripe",
     "careers_url": "https://stripe.com/jobs", "github_org": "stripe"},
    {"name": "Airbnb", "domain": "airbnb.com", "ats_type": "greenhouse", "ats_slug": "airbnb",
     "careers_url": "https://careers.airbnb.com/", "github_org": "airbnb"},
    {"name": "Figma", "domain": "figma.com", "ats_type": "greenhouse", "ats_slug": "figma",
     "careers_url": "https://www.figma.com/careers/", "github_org": "figma"},
    {"name": "Vercel", "domain": "vercel.com", "ats_type": "greenhouse", "ats_slug": "vercel",
     "careers_url": "https://vercel.com/careers", "github_org": "vercel"},
    {"name": "Mozilla", "domain": "mozilla.org", "ats_type": "greenhouse", "ats_slug": "mozilla",
     "careers_url": "https://www.mozilla.org/en-US/careers/", "github_org": "mozilla"},
    {"name": "Discord", "domain": "discord.com", "ats_type": "greenhouse", "ats_slug": "discord",
     "careers_url": "https://discord.com/careers", "github_org": "discord"},
    {"name": "Linear", "domain": "linear.app", "ats_type": "ashby", "ats_slug": "linear",
     "careers_url": "https://linear.app/careers", "github_org": "linear"},
    {"name": "Instacart", "domain": "instacart.com", "ats_type": "greenhouse", "ats_slug": "instacart",
     "careers_url": "https://instacart.careers/", "github_org": "Instacart"},
]

SEED: list[dict] = INDIAN_VERIFIED + INDIAN_UNVERIFIED + US_VERIFIED_PHASE1_TESTING


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = SessionLocal()
    try:
        existing = {d for (d,) in db.execute(select(Company.domain)).all() if d}
        added = 0
        for row in SEED:
            if row.get("domain") in existing:
                continue
            db.add(Company(**row))
            added += 1
        db.commit()
        log.info(
            "Seeded %d companies (%d already present); %d have verified ATS slugs",
            added,
            len(SEED) - added,
            len(INDIAN_VERIFIED) + len(US_VERIFIED_PHASE1_TESTING),
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
