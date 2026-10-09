"""Discover Flutter/Dart companies from GitHub, with no hardcoded company list.

The rest of the pipeline answers "is this known company hiring?". This collector
answers the question that has to come first: *which companies build in Flutter
at all?* It searches public Dart repositories, keeps the ones owned by an
Organization rather than a personal account, and introduces each org as a
company keyed on the domain the org publishes.

Why GitHub rather than pub.dev: pub.dev's verified publishers are overwhelmingly
Google's own (`flutter.dev`, `dart.dev`, `firebase.google.com`) and individual
developers' personal domains, which yields roughly five real employers. Dart
repositories owned by organizations yield hundreds.

What this does NOT do is decide whether the org is an employer. Open-source
projects (LocalSend, Flame, Spotube) look identical to companies here. The ATS
probe downstream is the filter: a project has no job board, a company does.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from app.collectors.base import BaseCollector
from app.config import settings

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# GitHub's search API caps any single query at 1000 results, so one broad query
# can never see more than its first 1000 repos. Splitting by star band makes
# each query small enough to page through completely, and together they cover
# the whole popularity range instead of just the famous head.
STAR_BANDS: list[str] = [
    "stars:>2000",
    "stars:500..2000",
    "stars:150..500",
    "stars:50..150",
    "stars:20..50",
]
PAGES_PER_BAND = 3
PER_PAGE = 100

# Authenticated search allows 30 requests/minute. Stay under it.
SEARCH_REQUESTS_PER_SECOND = 0.4

# Orgs whose "company domain" is really a code host, a funding page, or the
# Flutter project itself — they can never resolve to an employer's job board.
_NON_COMPANY_HOSTS = re.compile(
    r"(github\.(com|io)|gitlab\.com|patreon\.com|opencollective\.com|"
    r"ko-fi\.com|twitter\.com|x\.com|linktr\.ee|medium\.com|"
    r"flutter\.dev|dart\.dev|flutter\.cn)$",
    re.I,
)


def _domain_from_blog(blog: str | None) -> str | None:
    """Reduce an org's advertised URL to a bare registrable domain."""
    if not blog:
        return None
    blog = blog.strip()
    if not blog:
        return None
    # Org blogs are frequently written without a scheme ("firebase.google.com").
    parsed = urlparse(blog if "//" in blog else f"https://{blog}")
    host = (parsed.netloc or parsed.path).strip().lower()
    host = host.split("/")[0].removeprefix("www.")
    if not host or "." not in host:
        return None
    if _NON_COMPANY_HOSTS.search(host):
        return None
    return host


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


class DartOrgDiscovery(BaseCollector):
    """Yields candidate companies, not signals — see `discover()`."""

    def __init__(self) -> None:
        super().__init__(requests_per_second=SEARCH_REQUESTS_PER_SECOND)

    def source_name(self) -> str:
        return "dart_org_discovery"

    async def _get(self, url: str) -> Any | None:
        await self.rate_limiter.acquire("github")
        try:
            resp = await self.client.get(url, headers=_github_headers())
        except httpx.HTTPError:
            log.exception("GitHub GET failed: %s", url)
            return None
        if resp.status_code in (403, 404, 422):
            # 403 is the secondary rate limit; 422 is a search query GitHub
            # refused. Neither is worth raising for — skip and keep going.
            log.warning("GitHub %s for %s", resp.status_code, url)
            return None
        resp.raise_for_status()
        return resp.json()

    async def _orgs_owning_dart_repos(self) -> dict[str, int]:
        """Org login -> highest star count among its Dart repos."""
        orgs: dict[str, int] = {}
        for band in STAR_BANDS:
            for page in range(1, PAGES_PER_BAND + 1):
                query = f"language:Dart {band}"
                url = (
                    f"{GITHUB_API}/search/repositories"
                    f"?q={httpx.QueryParams({'q': query})['q']}"
                    f"&sort=stars&per_page={PER_PAGE}&page={page}"
                )
                data = await self._get(url)
                if not data:
                    break
                items = data.get("items") or []
                for repo in items:
                    owner = repo.get("owner") or {}
                    if owner.get("type") != "Organization":
                        continue
                    login = owner.get("login")
                    if not login:
                        continue
                    stars = int(repo.get("stargazers_count") or 0)
                    orgs[login] = max(orgs.get(login, 0), stars)
                if len(items) < PER_PAGE:
                    break
        return orgs

    async def discover(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Candidate companies, most-starred first.

        Each is `{name, domain, github_org, location, stars}`. Orgs without a
        usable company domain are dropped: without one there is nothing to key a
        company row on, and nothing to probe for a careers page.
        """
        orgs = await self._orgs_owning_dart_repos()
        log.info("Found %d organizations owning public Dart repositories", len(orgs))

        ranked = sorted(orgs.items(), key=lambda kv: -kv[1])
        if limit is not None:
            ranked = ranked[:limit]

        candidates: list[dict[str, Any]] = []
        for login, stars in ranked:
            org = await self._get(f"{GITHUB_API}/orgs/{login}")
            if not org:
                continue
            domain = _domain_from_blog(org.get("blog"))
            if not domain:
                continue
            candidates.append(
                {
                    "name": (org.get("name") or login).strip(),
                    "domain": domain,
                    "github_org": login,
                    "location": (org.get("location") or None),
                    "stars": stars,
                }
            )

        log.info("%d of %d orgs publish a usable company domain", len(candidates), len(ranked))
        return candidates

    async def collect(self, company) -> dict[str, Any]:
        # Discovery is global, not per-company — see `discover()`.
        return {"intent": [], "stack": []}
