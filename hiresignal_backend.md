# HireSignal — Backend Specification

## Overview

HireSignal backend is a FastAPI service that collects hiring intent signals from public structured sources (ATS JSON APIs, RSS feeds, GitHub, Hacker News, Wappalyzer), classifies them using the Claude API, fingerprints company tech stacks, scores companies by hiring probability, and serves matched results to the Flutter mobile app.

Database and auth are provided by **Supabase** (PostgreSQL 15 + GoTrue). The Flutter app reads directly from Supabase for list/detail queries and realtime subscriptions; the FastAPI service owns writes, scraping, scoring, and LLM calls.

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Framework | FastAPI 0.115+ | Async, auto OpenAPI docs |
| Language | Python 3.12 | Best ecosystem for scraping + AI |
| Database | Supabase (PostgreSQL 15) | Free tier, Row Level Security, realtime for Flutter, built-in auth |
| ORM | SQLAlchemy 2.0 + Alembic | Type-safe queries, migration management |
| Scheduling | GitHub Actions cron | Free; replaces paid Celery worker on Render |
| In-process queue | asyncio + httpx | Scrape fan-out inside a single GitHub Actions run — no Redis needed in Phase 1 |
| LLM | Claude API (Haiku for bulk classification, Sonnet for complex extraction) | Best accuracy-to-cost ratio |
| Scraping | httpx + BeautifulSoup4 + feedparser | Lightweight, async-capable |
| Web stack detection | python-Wappalyzer (self-hosted) | Free; no external API |
| APK Analysis | androguard | **Phase 2** — Flutter/RN/native detection from app binaries |
| Hosting | Render (free tier, web only) | Zero-config Python deployment |
| CI/CD | GitHub Actions | Auto-deploy on push to main + scheduled scrapers |

> **Why no Celery/Redis in Phase 1?** Render's free tier does not include background workers (worker dynos are paid). Instead, each scraping job is a Python script invoked by a scheduled GitHub Actions workflow. The FastAPI web service only handles HTTP requests (API for the Flutter app). This cuts hosting cost to $0 for Phase 1 and removes a whole class of "worker went to sleep" bugs.

---

## Project Structure

```
hiresignal_backend/
├── .github/
│   └── workflows/
│       ├── deploy.yml                 # Auto-deploy to Render on push to main
│       ├── scrape-ats.yml             # Daily ATS adapter run
│       ├── scrape-rss.yml             # Daily RSS feeds (Inc42, Entrackr, YourStory, blogs)
│       ├── scrape-github.yml          # Twice-weekly GitHub org scan
│       ├── scrape-hn.yml              # Monthly HN "Who's Hiring" ingest
│       ├── scrape-wappalyzer.yml      # Monthly Wappalyzer web-stack scan
│       ├── score.yml                  # Daily score + match refresh
│       └── validate.yml               # Weekly validation snapshot
├── alembic/
│   ├── versions/
│   └── env.py
├── app/
│   ├── __init__.py
│   ├── main.py                        # FastAPI app entry
│   ├── config.py                      # pydantic-settings
│   ├── database.py                    # SQLAlchemy session + Supabase client
│   ├── auth.py                        # Supabase JWT verification dependency
│   │
│   ├── models/                        # SQLAlchemy ORM
│   │   ├── company.py
│   │   ├── intent_signal.py
│   │   ├── stack_signal.py
│   │   ├── company_score.py
│   │   ├── user.py
│   │   └── match.py
│   │
│   ├── schemas/                       # Pydantic request/response
│   │   ├── company.py
│   │   ├── signal.py
│   │   ├── user.py
│   │   └── match.py
│   │
│   ├── api/
│   │   ├── router.py                  # Main aggregator
│   │   ├── companies.py
│   │   ├── signals.py
│   │   ├── matches.py
│   │   ├── users.py
│   │   └── health.py
│   │
│   ├── collectors/                    # Data collection (replaces old `scrapers/`)
│   │   ├── base.py                    # BaseCollector abstract
│   │   ├── ats/
│   │   │   ├── __init__.py
│   │   │   ├── base.py                # ATSAdapter abstract
│   │   │   ├── greenhouse.py
│   │   │   ├── lever.py
│   │   │   ├── ashby.py
│   │   │   ├── workable.py
│   │   │   ├── smartrecruiters.py
│   │   │   └── registry.py            # Maps company → adapter via `ats_type` field
│   │   ├── rss_scraper.py             # Inc42, Entrackr, YourStory + engineering blogs
│   │   ├── github_scraper.py          # Dependency fingerprinting + activity signal
│   │   ├── hn_whos_hiring.py          # Monthly HN API ingest
│   │   └── wappalyzer_scraper.py      # Self-hosted Wappalyzer for web stack
│   │
│   ├── processors/
│   │   ├── llm_classifier.py          # Claude API: classify/extract
│   │   ├── stack_fingerprinter.py
│   │   ├── scoring_engine.py
│   │   └── match_engine.py
│   │
│   ├── jobs/                          # Standalone entry points invoked by GH Actions
│   │   ├── run_ats.py
│   │   ├── run_rss.py
│   │   ├── run_github.py
│   │   ├── run_hn.py
│   │   ├── run_wappalyzer.py
│   │   ├── run_scoring.py
│   │   └── run_validation.py
│   │
│   └── utils/
│       ├── rate_limiter.py
│       └── text_cleaner.py
│
├── scripts/
│   ├── seed_companies.py              # Seed initial 50 companies + ats_type discovery
│   └── discover_ats.py                # Helper: open a careers URL and guess ATS
│
├── tests/
│   ├── test_collectors/
│   ├── test_processors/
│   └── test_api/
│
├── .env.example
├── .gitignore
├── alembic.ini
├── Dockerfile
├── docker-compose.yml                 # Local dev: FastAPI only (no Redis needed)
├── requirements.txt
├── requirements-dev.txt
├── render.yaml
└── README.md
```

---

## Database Schema (Supabase PostgreSQL)

### Table: `companies`
```sql
CREATE TABLE companies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    domain          TEXT UNIQUE,
    careers_url     TEXT,
    ats_type        TEXT,                    -- 'greenhouse' | 'lever' | 'ashby' | 'workable' | 'smartrecruiters' | 'other'
    ats_slug        TEXT,                    -- company identifier within the ATS
    github_org      TEXT,
    app_package_id  TEXT,                    -- Phase 2
    employee_count  INTEGER,
    industry        TEXT,
    location        TEXT,
    website         TEXT,
    logo_url        TEXT,
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_companies_domain ON companies(domain);
CREATE INDEX idx_companies_active ON companies(is_active) WHERE is_active = true;
CREATE INDEX idx_companies_ats ON companies(ats_type, ats_slug);
```

> `linkedin_slug` and `employee_count_prev` from the original schema are removed — LinkedIn headcount tracking is deferred to Phase 2.

### Table: `intent_signals`
```sql
CREATE TABLE intent_signals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID REFERENCES companies(id) ON DELETE CASCADE,
    signal_type     TEXT NOT NULL,         -- 'ats_job' | 'funding' | 'news' | 'hn_whos_hiring' | 'github_activity'
    source          TEXT NOT NULL,         -- URL or API name
    raw_data        JSONB,
    extracted       JSONB,                 -- Claude-processed structured output
    confidence      REAL DEFAULT 0.0,
    detected_at     TIMESTAMPTZ DEFAULT now(),
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_signals_company ON intent_signals(company_id);
CREATE INDEX idx_signals_type ON intent_signals(signal_type);
CREATE INDEX idx_signals_detected ON intent_signals(detected_at DESC);
```

### Table: `stack_signals`
```sql
CREATE TABLE stack_signals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID REFERENCES companies(id) ON DELETE CASCADE,
    source_type     TEXT NOT NULL,         -- 'github' | 'ats_job_nlp' | 'wappalyzer' | 'blog' | 'apk' (Phase 2)
    source_url      TEXT,
    technologies    JSONB NOT NULL,        -- {"flutter": 0.95, "python": 0.8, ...}
    raw_evidence    TEXT,
    detected_at     TIMESTAMPTZ DEFAULT now(),
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_stack_company ON stack_signals(company_id);
```

### Table: `company_scores`
```sql
CREATE TABLE company_scores (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id          UUID UNIQUE REFERENCES companies(id) ON DELETE CASCADE,
    intent_score        REAL DEFAULT 0.0,
    stack_fingerprint   JSONB,
    signal_count        INTEGER DEFAULT 0,
    strongest_signal    TEXT,
    last_scored_at      TIMESTAMPTZ DEFAULT now(),
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_scores_intent ON company_scores(intent_score DESC);
```

### Table: `users`
```sql
CREATE TABLE users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_id             UUID UNIQUE,       -- Supabase Auth user ID
    email               TEXT UNIQUE NOT NULL,
    name                TEXT,
    skills              JSONB NOT NULL DEFAULT '{}',
    experience_years    INTEGER,
    preferred_locations JSONB DEFAULT '[]',
    min_salary          INTEGER,           -- monthly INR
    is_active           BOOLEAN DEFAULT true,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);
```

### Table: `matches`
```sql
CREATE TABLE matches (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    company_id      UUID REFERENCES companies(id) ON DELETE CASCADE,
    score           REAL NOT NULL,
    tech_fit        REAL NOT NULL,
    intent_score    REAL NOT NULL,
    top_signals     JSONB,
    status          TEXT DEFAULT 'new',   -- 'new' | 'viewed' | 'saved' | 'applied' | 'dismissed'
    matched_at      TIMESTAMPTZ DEFAULT now(),
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, company_id)
);

CREATE INDEX idx_matches_user ON matches(user_id);
CREATE INDEX idx_matches_score ON matches(score DESC);
```

### Table: `validation_snapshots` (new — for Phase 1 accuracy tracking)
```sql
CREATE TABLE validation_snapshots (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    taken_at        TIMESTAMPTZ DEFAULT now(),
    top_n           INTEGER DEFAULT 20,
    predictions     JSONB NOT NULL,       -- [{"company_id": "...", "score": 87, "rank": 1}, ...]
    labeled_at      TIMESTAMPTZ,
    labels          JSONB,                -- [{"company_id": "...", "actually_hiring": true, "notes": "..."}, ...]
    precision_at_10 REAL,
    precision_at_20 REAL
);
```

### Row Level Security (RLS)

```sql
-- Companies, signals, scores: readable by any authenticated user
ALTER TABLE companies         ENABLE ROW LEVEL SECURITY;
ALTER TABLE intent_signals    ENABLE ROW LEVEL SECURITY;
ALTER TABLE stack_signals     ENABLE ROW LEVEL SECURITY;
ALTER TABLE company_scores    ENABLE ROW LEVEL SECURITY;

CREATE POLICY "authenticated read" ON companies      FOR SELECT TO authenticated USING (true);
CREATE POLICY "authenticated read" ON intent_signals FOR SELECT TO authenticated USING (true);
CREATE POLICY "authenticated read" ON stack_signals  FOR SELECT TO authenticated USING (true);
CREATE POLICY "authenticated read" ON company_scores FOR SELECT TO authenticated USING (true);

-- Users and matches: only the owner
ALTER TABLE users   ENABLE ROW LEVEL SECURITY;
ALTER TABLE matches ENABLE ROW LEVEL SECURITY;

CREATE POLICY "own user row"   ON users   FOR ALL TO authenticated USING (auth_id = auth.uid());
CREATE POLICY "own matches"    ON matches FOR ALL TO authenticated
    USING (user_id IN (SELECT id FROM users WHERE auth_id = auth.uid()));

-- All writes go through FastAPI with the service key (bypasses RLS).
```

---

## Environment Variables

```env
# .env.example

# Supabase
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_KEY=eyJ...              # server-only, bypasses RLS
DATABASE_URL=postgresql://postgres:password@db.xxxxx.supabase.co:5432/postgres

# Claude API
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_HAIKU_MODEL=claude-haiku-4-5
CLAUDE_SONNET_MODEL=claude-sonnet-4-6

# GitHub (for scraping + the Actions-generated token in CI uses GITHUB_TOKEN)
GITHUB_TOKEN=ghp_xxxxx                   # Personal token for repo dependency reads

# App
APP_ENV=development
LOG_LEVEL=INFO
SCRAPE_RATE_LIMIT=2                      # seconds between requests per domain
MAX_COMPANIES_PER_RUN=50
```

> **Removed from Phase 1:** `SERPAPI_KEY`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `REDIS_URL`.

---

## API Endpoints

### Health
```
GET  /health                           → {"status": "ok", "db": "connected"}
GET  /health/collectors                → {"last_run": {...}, "signals_last_24h": 123}
```

### Companies
```
GET  /api/v1/companies                 → List companies with scores
     ?sort=intent_score|name
     ?min_score=50
     ?tech=flutter,python
     ?limit=20&offset=0

GET  /api/v1/companies/{id}            → Company detail with all signals and stack

POST /api/v1/companies                 → Add a company to track (admin only)
     Body: {"name": "...", "domain": "...", "careers_url": "...",
            "ats_type": "lever", "ats_slug": "razorpay", "github_org": "..."}
```

### Signals
```
GET  /api/v1/companies/{id}/signals    → All signals for a company
     ?type=ats_job|funding|news|hn_whos_hiring|github_activity
     ?since=2026-01-01

GET  /api/v1/signals/recent            → Latest signals across all companies
     ?limit=50
```

### User & Matching
```
POST /api/v1/users/profile             → Create/update profile (requires Supabase JWT)
     Body: {"name": "...", "skills": {"flutter": 0.9, ...}, "experience_years": 5,
            "preferred_locations": ["Remote"]}

GET  /api/v1/matches                   → Personalized matches for authenticated user
     ?min_score=30&min_tech_fit=0.5&limit=20

POST /api/v1/matches/refresh           → Trigger re-computation of matches

PATCH /api/v1/matches/{id}             → Update match status
      Body: {"status": "saved" | "applied" | "dismissed"}
```

### Admin (service token required)
```
POST /api/v1/admin/collectors/trigger  → Manually invoke a specific collector
     Body: {"collector": "ats" | "rss" | "github" | "hn" | "wappalyzer" | "scoring",
            "company_id": "..." | null}

GET  /api/v1/admin/collectors/status   → Last run per collector
```

---

## Signal Collector Architecture

All collectors inherit from `BaseCollector`, write rows to `intent_signals` and/or `stack_signals`, and are invoked as standalone jobs from `app/jobs/run_*.py` (which GitHub Actions runs on a cron).

### Base collector

```python
# app/collectors/base.py

from abc import ABC, abstractmethod
import httpx
from app.utils.rate_limiter import RateLimiter

class BaseCollector(ABC):
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "HireSignal/1.0 (hiring-intent-research)"},
            follow_redirects=True,
        )
        self.rate_limiter = RateLimiter(requests_per_second=0.5)

    @abstractmethod
    async def collect(self, company) -> dict:
        """Return {'intent': [...], 'stack': [...]} rows to insert."""

    @abstractmethod
    def source_name(self) -> str: ...
```

### ATS adapter architecture (the Phase 1 workhorse)

Public JSON job boards replace all career-page HTML scraping. One adapter per ATS, same interface, dispatched by `company.ats_type`.

```python
# app/collectors/ats/base.py

class ATSAdapter(ABC):
    @abstractmethod
    async def fetch_jobs(self, ats_slug: str) -> list[dict]:
        """Return normalized job dicts: {title, location, department, description, posted_at, url}."""

    @abstractmethod
    def ats_name(self) -> str: ...
```

```python
# app/collectors/ats/greenhouse.py
class GreenhouseAdapter(ATSAdapter):
    BASE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    def ats_name(self) -> str: return "greenhouse"
    async def fetch_jobs(self, ats_slug):
        resp = await client.get(self.BASE.format(slug=ats_slug))
        data = resp.json()
        return [self._normalize(job) for job in data.get("jobs", [])]
    def _normalize(self, job):
        return {
            "title": job["title"],
            "location": job.get("location", {}).get("name"),
            "department": (job.get("departments") or [{}])[0].get("name"),
            "description": _html_to_text(job.get("content", "")),
            "posted_at": job["updated_at"],
            "url": job["absolute_url"],
            "external_id": str(job["id"]),
        }
```

```python
# app/collectors/ats/lever.py
# Endpoint: https://api.lever.co/v0/postings/{slug}?mode=json

# app/collectors/ats/ashby.py
# Endpoint: https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true

# app/collectors/ats/workable.py
# Endpoint: https://apply.workable.com/api/v3/accounts/{slug}/jobs

# app/collectors/ats/smartrecruiters.py
# Endpoint: https://api.smartrecruiters.com/v1/companies/{slug}/postings
```

```python
# app/collectors/ats/registry.py

ADAPTERS = {
    "greenhouse":      GreenhouseAdapter(),
    "lever":           LeverAdapter(),
    "ashby":           AshbyAdapter(),
    "workable":        WorkableAdapter(),
    "smartrecruiters": SmartRecruitersAdapter(),
}

def get_adapter(ats_type: str) -> ATSAdapter | None:
    return ADAPTERS.get(ats_type)
```

**Per company → per ATS run:**
1. `ADAPTERS[company.ats_type].fetch_jobs(company.ats_slug)` → list of jobs
2. Count of jobs → `intent_signals(type='ats_job', confidence=min(1.0, count/5))`
3. Each job description → Claude Haiku → `stack_signals(source_type='ats_job_nlp')`

> **Companies on Workday or Darwinbox have no public JSON board.** Flag them with `ats_type='other'` and skip in Phase 1. They become candidates for Playwright-based scraping in Phase 2.

### RSS scraper (Indian funding & news)

```python
# app/collectors/rss_scraper.py

FEEDS = {
    "inc42":       "https://inc42.com/feed/",
    "entrackr":    "https://entrackr.com/feed/",
    "yourstory":   "https://yourstory.com/feed",
    # Add per-company engineering blogs here as discovered:
    # "razorpay_eng": "https://razorpay.com/blog/engineering/feed/",
}

async def run():
    for name, url in FEEDS.items():
        feed = feedparser.parse(url)
        for entry in feed.entries:
            matched_companies = _match_companies(entry.title + " " + entry.summary)
            for company in matched_companies:
                classification = await claude_classify(
                    company.name, "news_or_funding", entry.summary
                )
                if classification["has_hiring_signal"]:
                    insert_intent_signal(
                        company_id=company.id,
                        signal_type=classification["signal_type"],  # 'funding' | 'news'
                        source=entry.link,
                        confidence=classification["confidence"],
                        extracted=classification,
                    )
```

### GitHub scraper (stack + intent)

```python
# app/collectors/github_scraper.py

DEPENDENCY_MAP = {
    "pubspec.yaml":    {"flutter": 0.95, "dart": 0.95},
    "requirements.txt":{"python": 0.9},
    "Pipfile":         {"python": 0.9},
    "pyproject.toml":  {"python": 0.9},
    "package.json":    {"javascript": 0.8},
    "go.mod":          {"go": 0.95},
    "Cargo.toml":      {"rust": 0.95},
    "build.gradle":    {"kotlin": 0.7, "java": 0.7},
    "Gemfile":         {"ruby": 0.9},
    "composer.json":   {"php": 0.9},
    "pom.xml":         {"java": 0.9},
    "Package.swift":   {"swift": 0.95},
    "Dockerfile":      {},   # parse FROM lines for base images
}

PACKAGE_TECH_MAP = {
    # Python
    "fastapi": ("fastapi", 0.9), "django": ("django", 0.9), "flask": ("flask", 0.9),
    "celery": ("celery", 0.7),   "sqlalchemy": ("sqlalchemy", 0.7),
    "tensorflow": ("tensorflow", 0.9), "torch": ("pytorch", 0.9),
    "langchain": ("langchain", 0.8),
    # Node
    "react": ("react", 0.9),  "next": ("nextjs", 0.9),  "vue": ("vue", 0.9),
    "express": ("express", 0.8), "nestjs": ("nestjs", 0.9),
    # Flutter
    "firebase_core": ("firebase", 0.8), "supabase_flutter": ("supabase", 0.8),
    "flutter_bloc": ("bloc", 0.8), "get_it": ("get_it", 0.6),
}

# Intent signal from GitHub:
#  - new repo created in last 30 days  → github_activity, confidence 0.5
#  - contributor count delta > 20%     → github_activity, confidence 0.7
#  - "hiring" in README of any repo    → github_activity, confidence 0.9
```

### Hacker News "Who's Hiring" collector

```python
# app/collectors/hn_whos_hiring.py
# Monthly: the first Monday thread titled "Ask HN: Who is hiring? (Month YYYY)"
# https://hn.algolia.com/api/v1/search?query=who+is+hiring&tags=story

async def run():
    story = await _find_latest_whos_hiring_thread()
    comments = await _fetch_all_comments(story["objectID"])
    for comment in comments:
        parsed = await claude_classify_hn_comment(comment["text"])
        # parsed → {company, location, remote, technologies[], roles[]}
        company = await _resolve_or_create_company(parsed["company"])
        insert_intent_signal(
            company_id=company.id,
            signal_type="hn_whos_hiring",
            source=f"https://news.ycombinator.com/item?id={comment['objectID']}",
            confidence=0.85,
            extracted=parsed,
        )
        for tech in parsed["technologies"]:
            insert_stack_signal(
                company_id=company.id,
                source_type="hn_whos_hiring",
                technologies={tech: 0.8},
                raw_evidence=comment["text"][:500],
            )
```

### Wappalyzer collector (self-hosted)

```python
# app/collectors/wappalyzer_scraper.py
# Uses python-Wappalyzer. No external API; runs headless against company.domain.

from Wappalyzer import Wappalyzer, WebPage

wappalyzer = Wappalyzer.latest()

async def collect(company):
    if not company.domain:
        return
    page = WebPage.new_from_url(f"https://{company.domain}")
    detections = wappalyzer.analyze_with_versions_and_categories(page)
    techs = {_normalize(name): 0.7 for name in detections}  # web-stack confidence 0.7
    insert_stack_signal(
        company_id=company.id,
        source_type="wappalyzer",
        source_url=f"https://{company.domain}",
        technologies=techs,
    )
```

### APK analyzer — **Phase 2 (deferred)**

Blocker is APK sourcing, not detection. Google Play has no public download API; mirrors (APKPure, APKMirror) have anti-bot measures. In Phase 1, mobile stack is inferred from ATS job descriptions (`flutter` / `kotlin` / `swift` keywords) and GitHub dependency files, which cover ~90% of cases.

---

## Scoring Engine

### Weights and decay

```python
# app/processors/scoring_engine.py

SIGNAL_WEIGHTS = {
    "ats_job":          40,  # Direct open-role evidence (strongest in Phase 1)
    "funding":          30,  # Strong leading indicator
    "hn_whos_hiring":   15,  # Self-declared hiring, max 1 month old
    "news":             10,  # Expansion / product launch
    "github_activity":   5,  # New repos / contributor growth
}

DECAY_RATES = {   # exponential: value * e^(-rate * days_old)
    "ats_job":         0.05,  # ~20-day half-life
    "funding":         0.02,  # ~50 days
    "hn_whos_hiring":  0.04,  # ~25 days (monthly thread)
    "news":            0.04,  # ~25 days
    "github_activity": 0.03,  # ~33 days
}
```

### Intent score

```python
def calculate_intent_score(signals: list[IntentSignal]) -> float:
    total = 0.0
    for s in signals:
        days_old = (now() - s.detected_at).days
        decay = math.exp(-DECAY_RATES[s.signal_type] * days_old)
        total += SIGNAL_WEIGHTS[s.signal_type] * s.confidence * decay
    return min(total, 100.0)
```

### Tech fit (cosine similarity)

```python
def calculate_tech_fit(user_skills: dict, company_stack: dict) -> float:
    all_techs = set(user_skills) | set(company_stack)
    u = [user_skills.get(t, 0.0) for t in all_techs]
    c = [company_stack.get(t, 0.0) for t in all_techs]
    dot = sum(a*b for a, b in zip(u, c))
    mag_u, mag_c = math.sqrt(sum(x*x for x in u)), math.sqrt(sum(x*x for x in c))
    return 0.0 if (mag_u == 0 or mag_c == 0) else dot / (mag_u * mag_c)

def compute_match_score(intent_score: float, tech_fit: float) -> float:
    # Tech fit matters more — a hiring company in the wrong stack is useless.
    return (0.4 * intent_score) + (0.6 * tech_fit * 100)
```

### Stack fingerprint aggregation

Per technology, take `max(confidence)` across all `stack_signals` sources, with a per-source cap:

| Source | Max confidence |
|---|---|
| `github` (dependency file) | 1.0 |
| `ats_job_nlp` (LLM on job description) | 0.9 |
| `wappalyzer` (headers + JS bundle) | 0.7 |
| `blog` / `hn_whos_hiring` | 0.8 |
| `apk` (Phase 2) | 0.95 |

---

## Claude API Integration

```python
# app/processors/llm_classifier.py

SIGNAL_CLASSIFICATION_PROMPT = """
Analyze content about the company "{company_name}".

Source: {source_type}
Content:
{content}

Return JSON only:
{{
  "has_hiring_signal": true/false,
  "signal_type": "funding" | "news" | "ats_job" | "hn_whos_hiring" | "none",
  "confidence": 0.0-1.0,
  "roles_mentioned": [...],
  "technologies_mentioned": [...],
  "evidence": "direct quote",
  "summary": "one sentence"
}}

Rules:
- has_hiring_signal=true only with genuine current/imminent hiring evidence.
- technologies_mentioned must be specific tech names (normalize: "React.js" → "react").
- No markdown. JSON only.
"""

STACK_EXTRACTION_PROMPT = """
Extract technologies from this job posting for "{company_name}".

Content:
{content}

Return JSON only:
{{
  "technologies": {{"tech_name": 0.0-1.0}},
  "categories": {{
    "frontend": [], "backend": [], "mobile": [], "database": [], "cloud": [], "devops": []
  }}
}}

Confidence rules:
- Required (must-have): 0.9
- Preferred (nice-to-have): 0.5
- Inferred from context: 0.3

Normalize names (lowercase, no versions). No markdown.
"""
```

**Model choice:**
- `claude-haiku-4-5` for bulk classification (every job description, every RSS entry).
- `claude-sonnet-4-6` only for ambiguous HN comments or long engineering blog posts (gated behind length > 2000 chars).

---

## GitHub Actions Scheduling

Replaces Celery Beat. Each workflow checks out the repo, installs deps, runs a single `app/jobs/run_*.py` script, and exits.

```yaml
# .github/workflows/scrape-ats.yml
name: scrape-ats
on:
  schedule:
    - cron: "30 0 * * *"      # 06:00 IST
  workflow_dispatch:
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -r requirements.txt
      - run: python -m app.jobs.run_ats
        env:
          DATABASE_URL:       ${{ secrets.DATABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
          ANTHROPIC_API_KEY:  ${{ secrets.ANTHROPIC_API_KEY }}
          GITHUB_TOKEN:       ${{ secrets.PAT_TOKEN }}
```

| Workflow | Cron (UTC) | IST | Purpose |
|---|---|---|---|
| `scrape-ats.yml` | `30 0 * * *` | 06:00 daily | Fetch all ATS boards for active companies |
| `scrape-rss.yml` | `30 2 * * *` | 08:00 daily | Inc42 / Entrackr / YourStory + blog feeds |
| `scrape-github.yml` | `30 1 * * 1,4` | 07:00 Mon+Thu | Dependency files + activity signal |
| `scrape-hn.yml` | `0 6 1 * *` | 11:30 1st of month | HN "Who's Hiring" ingest |
| `scrape-wappalyzer.yml` | `0 5 1 * *` | 10:30 1st of month | Web stack fingerprint |
| `score.yml` | `30 4 * * *` | 10:00 daily | Recompute `company_scores`, refresh `matches` |
| `validate.yml` | `0 3 * * 1` | 08:30 Mon | Snapshot top-20 predictions for later labeling |

GitHub Actions free tier: 2,000 min/month for private repos; unlimited for public. These jobs run <10 min total/day.

---

## Deployment

### Render — web only

```yaml
# render.yaml
services:
  - type: web
    name: hiresignal-api
    runtime: python
    buildCommand: pip install -r requirements.txt && alembic upgrade head
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    plan: free
    envVars:
      - key: PYTHON_VERSION
        value: "3.12"
      - key: DATABASE_URL
        sync: false
      - key: SUPABASE_URL
        sync: false
      - key: SUPABASE_SERVICE_KEY
        sync: false
      - key: ANTHROPIC_API_KEY
        sync: false
```

> No worker service. Render free tier does not support background workers. All scheduled work runs via GitHub Actions.

### Local dev (Docker)

```yaml
# docker-compose.yml
services:
  api:
    build: .
    ports: ["8000:8000"]
    env_file: .env
    volumes: [./app:/code/app]
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

No Redis container needed in Phase 1.

---

## Requirements

```txt
# requirements.txt

# Core
fastapi==0.115.6
uvicorn[standard]==0.34.0
pydantic==2.10.4
pydantic-settings==2.7.1

# Database
sqlalchemy==2.0.36
alembic==1.14.1
psycopg2-binary==2.9.10
supabase==2.11.0

# HTTP & parsing
httpx==0.28.1
beautifulsoup4==4.12.3
lxml==5.3.0
feedparser==6.0.11

# GitHub
PyGithub==2.5.0

# Web stack detection
python-Wappalyzer==0.4.2

# LLM
anthropic==0.42.0

# NLP & matching
scikit-learn==1.6.0
numpy==2.2.1

# Observability
structlog==24.4.0
sentry-sdk[fastapi]==2.19.2
```

> **Removed:** `celery`, `redis`, `androguard` (Phase 2).

---

## Validation Harness

Signal quality is only trusted if measured. The `validate.yml` workflow snapshots the top-20 ranked companies weekly; a human labels them 14 days later; the system reports precision.

```python
# app/jobs/run_validation.py (runs weekly)
def snapshot():
    top = db.query(CompanyScore).order_by(CompanyScore.intent_score.desc()).limit(20).all()
    predictions = [{"company_id": s.company_id, "score": s.intent_score, "rank": i+1}
                   for i, s in enumerate(top)]
    db.insert(ValidationSnapshot(predictions=predictions))
```

**Labeling flow (manual, in Supabase SQL editor or Retool):**
1. Pull `validation_snapshots` where `taken_at` is 14 days old and `labels IS NULL`.
2. For each prediction, open the company's careers page or LinkedIn Jobs and mark `actually_hiring: true/false`.
3. Compute `precision_at_10` and `precision_at_20`.
4. If precision drops below 0.5, tune `SIGNAL_WEIGHTS` or improve a collector.

Phase 1 exits when `precision_at_10 ≥ 0.6` for 2 consecutive weeks.

---

## Phase 1 Scope

See `hiresignal_phase1.md` (in the Flutter frontend repo for cross-reference) for the week-by-week plan. Backend-side Phase 1 covers: schema, ATS adapters, RSS collector, GitHub collector, HN collector, Wappalyzer collector, scoring engine, match engine, FastAPI endpoints, Supabase RLS, GitHub Actions scheduling, and validation harness.

**Not in Phase 1:**
- APK binary analysis (`androguard`)
- Playwright for Workday/Darwinbox career pages
- LinkedIn headcount tracking + key-departure detection
- Celery / Redis
- Admin dashboard
- Push notifications
