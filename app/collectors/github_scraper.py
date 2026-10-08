"""GitHub-based stack + intent collector.

Stack: parse dependency-manifest files in each public repo.
Intent: new repos in last 30 days, contributor-count growth, "hiring" in README.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.collectors.base import BaseCollector
from app.config import settings
from app.models.company import Company

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

DEPENDENCY_MAP: dict[str, dict[str, float]] = {
    "pubspec.yaml": {"flutter": 0.95, "dart": 0.95},
    "requirements.txt": {"python": 0.9},
    "Pipfile": {"python": 0.9},
    "pyproject.toml": {"python": 0.9},
    "package.json": {"javascript": 0.8},
    "go.mod": {"go": 0.95},
    "Cargo.toml": {"rust": 0.95},
    "build.gradle": {"kotlin": 0.7, "java": 0.7},
    "Gemfile": {"ruby": 0.9},
    "composer.json": {"php": 0.9},
    "pom.xml": {"java": 0.9},
    "Package.swift": {"swift": 0.95},
    "Dockerfile": {},
}

PACKAGE_TECH_MAP: dict[str, tuple[str, float]] = {
    # Python
    "fastapi": ("fastapi", 0.9), "django": ("django", 0.9), "flask": ("flask", 0.9),
    "celery": ("celery", 0.7), "sqlalchemy": ("sqlalchemy", 0.7),
    "tensorflow": ("tensorflow", 0.9), "torch": ("pytorch", 0.9),
    "langchain": ("langchain", 0.8),
    # Node
    "react": ("react", 0.9), "next": ("nextjs", 0.9), "vue": ("vue", 0.9),
    "express": ("express", 0.8), "nestjs": ("nestjs", 0.9),
    # Flutter
    "firebase_core": ("firebase", 0.8), "supabase_flutter": ("supabase", 0.8),
    "flutter_bloc": ("bloc", 0.8), "get_it": ("get_it", 0.6),
}

HIRING_RE = re.compile(r"\b(hiring|we're hiring|join (our|the) team|open roles?|careers?)\b", re.I)


def _github_headers() -> dict[str, str]:
    token = settings.github_token
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# The GitHub REST API allows 5,000 requests/hour with a token (~1.4/sec
# sustained). Bursting a few per second for the few minutes this job runs stays
# far inside that budget, and is ~6x faster than the HTML-scraping default.
GITHUB_REQUESTS_PER_SECOND = 3.0

# Repos are listed `sort=pushed`, so the first N are the most recently active —
# the ones whose dependencies reflect what the company works in today.
MAX_REPOS_PER_COMPANY = 10


class GitHubCollector(BaseCollector):
    def __init__(self) -> None:
        super().__init__(requests_per_second=GITHUB_REQUESTS_PER_SECOND)

    def source_name(self) -> str:
        return "github"

    async def _get(self, url: str) -> httpx.Response | None:
        await self.rate_limiter.acquire("github")
        try:
            resp = await self.client.get(url, headers=_github_headers())
        except httpx.HTTPError:
            log.exception("GitHub GET failed: %s", url)
            return None
        if resp.status_code == 404:
            return None
        if resp.status_code == 403:
            log.warning("GitHub rate limited at %s", url)
            return None
        resp.raise_for_status()
        return resp

    async def _list_repos(self, org: str) -> list[dict]:
        resp = await self._get(f"{GITHUB_API}/orgs/{org}/repos?per_page=100&sort=pushed")
        if resp is None:
            # Fall back to user endpoint — some "orgs" are personal accounts.
            resp = await self._get(f"{GITHUB_API}/users/{org}/repos?per_page=100&sort=pushed")
        return resp.json() if resp else []

    async def _list_root_files(self, repo_full: str) -> set[str]:
        """Filenames at the repo root, in one request.

        Probing each known manifest name blindly costs one request per name per
        repo (and most of them 404). Listing the root once lets us fetch only
        the manifests that actually exist.
        """
        resp = await self._get(f"{GITHUB_API}/repos/{repo_full}/contents")
        if resp is None:
            return set()
        try:
            entries = resp.json()
        except ValueError:
            return set()
        if not isinstance(entries, list):
            return set()
        return {e["name"] for e in entries if isinstance(e, dict) and e.get("type") == "file"}

    async def _fetch_file(self, repo_full: str, path: str) -> str | None:
        resp = await self._get(f"{GITHUB_API}/repos/{repo_full}/contents/{path}")
        if resp is None:
            return None
        data = resp.json()
        content = data.get("content")
        encoding = data.get("encoding")
        if not content:
            return None
        if encoding == "base64":
            try:
                return base64.b64decode(content).decode("utf-8", errors="ignore")
            except Exception:  # noqa: BLE001
                return None
        return content

    def _parse_packages(self, filename: str, text: str) -> dict[str, float]:
        out: dict[str, float] = {}
        lower_text = text.lower()
        if filename == "package.json":
            try:
                pkg = json.loads(text)
            except json.JSONDecodeError:
                return out
            deps = {}
            deps.update(pkg.get("dependencies", {}) or {})
            deps.update(pkg.get("devDependencies", {}) or {})
            for name in deps:
                key = name.lower().split("/")[-1]
                if key in PACKAGE_TECH_MAP:
                    tech, conf = PACKAGE_TECH_MAP[key]
                    out[tech] = max(out.get(tech, 0.0), conf)
        else:
            for key, (tech, conf) in PACKAGE_TECH_MAP.items():
                if key in lower_text:
                    out[tech] = max(out.get(tech, 0.0), conf)
        return out

    async def collect(self, company: Company) -> dict[str, Any]:
        if not company.github_org:
            return {"intent": [], "stack": []}

        repos = await self._list_repos(company.github_org)
        if not repos:
            return {"intent": [], "stack": []}

        now = datetime.now(timezone.utc)
        thirty_days_ago = now - timedelta(days=30)
        intent_rows: list[dict] = []
        stack_rows: list[dict] = []

        new_repos: list[str] = []
        hiring_hits: list[str] = []

        for repo in repos[:MAX_REPOS_PER_COMPANY]:
            full = repo.get("full_name")
            if not full:
                continue
            created_at = repo.get("created_at")
            if created_at:
                try:
                    created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    if created_dt >= thirty_days_ago:
                        new_repos.append(full)
                except ValueError:
                    pass

            root_files = await self._list_root_files(full)

            techs: dict[str, float] = {}
            for filename in DEPENDENCY_MAP.keys() & root_files:
                static_techs = DEPENDENCY_MAP[filename]
                # A manifest's presence alone is evidence of its language, even
                # if the body turns out to be unreadable.
                for tech, conf in static_techs.items():
                    techs[tech] = max(techs.get(tech, 0.0), conf)
                content = await self._fetch_file(full, filename)
                if content is None:
                    continue
                for tech, conf in self._parse_packages(filename, content).items():
                    techs[tech] = max(techs.get(tech, 0.0), conf)

            if techs:
                stack_rows.append(
                    {
                        "company_id": company.id,
                        "source_type": "github",
                        "source_url": repo.get("html_url"),
                        "technologies": techs,
                        "raw_evidence": f"deps in {full}",
                        "detected_at": now,
                    }
                )

            if "README.md" in root_files:
                readme = await self._fetch_file(full, "README.md")
                if readme and HIRING_RE.search(readme):
                    hiring_hits.append(full)

        if new_repos:
            intent_rows.append(
                {
                    "company_id": company.id,
                    "signal_type": "github_activity",
                    "source": f"github:{company.github_org}:new_repos",
                    "raw_data": {"new_repos": new_repos},
                    "extracted": {"new_repo_count": len(new_repos)},
                    "confidence": 0.5,
                    "detected_at": now,
                }
            )

        if hiring_hits:
            intent_rows.append(
                {
                    "company_id": company.id,
                    "signal_type": "github_activity",
                    "source": f"github:{company.github_org}:readme_hiring",
                    "raw_data": {"repos": hiring_hits},
                    "extracted": {"evidence": "hiring keyword in README"},
                    "confidence": 0.9,
                    "detected_at": now,
                }
            )

        return {"intent": intent_rows, "stack": stack_rows}
