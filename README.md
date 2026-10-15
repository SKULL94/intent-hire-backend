# HireSignal — Backend

**One question:** which companies hire Flutter developers, are reachable from
Delhi NCR or remote, and which of those are about to hire?

An opening is deliberately *not* required. "This company builds in Flutter" is a
durable fact written into their shipped product. "This company has a vacancy
today" is a perishable one that LinkedIn and Naukri already sell, badly. So this
service collects evidence of the first and leading indicators of the second, and
answers both through a single endpoint.

FastAPI + Supabase (Postgres, auth). Collection runs on GitHub Actions cron.
No LLM: every extraction is deterministic regex, so a run is reproducible and
costs nothing per posting.

## The two things it tracks

**Does this company hire Flutter?** — `stack_signals`, in descending order of
how much they prove:

| Evidence | Confidence | Collector |
| --- | --- | --- |
| `libflutter.so` in their shipped APK | proof | *not built yet* |
| Verified Dart packages on pub.dev | proof | *not built yet* |
| Posting whose **title** names Flutter | 0.95 | `run_adzuna` — the only live source |

Evidence must be **title-grade**. A description that merely mentions Flutter is
not evidence: body-only matching produced Airbnb, Cognizant, McAfee and Netgear
as "Flutter companies", and Flutter International PLC — a gambling group —
qualified on 16 postings purely because its own name appears in its own job
descriptions. Technologies are now detected with the company name censored, and
only title matches count. That cut the list from 101 companies to 57 real ones.

**Are they about to hire?** — not answered yet. `intent_signals` currently holds
only `ats_job` rows (Adzuna saw a Flutter posting), which means "hiring now", not
"about to hire".

The RSS collector used to fill this half and was removed: it produced 33 funded
companies with **zero** overlap against the 69 with Flutter evidence, and funding
articles cannot reveal a tech stack — asked to name technologies, Claude returned
"ai", "ev", "electric motorcycles", "adaptogens". Business categories, never a
codebase.

The APK scanner is what closes this: "a new Flutter app appeared where they used
to ship native" is Flutter evidence and a hiring signal in one observation.

## Local setup — one command

```bash
./scripts/dev.sh
```

Creates a `.venv`, installs `requirements-dev.txt`, applies Alembic migrations,
and starts the server on <http://localhost:8000> (Swagger UI at `/docs`). On
first run it copies `.env.example` → `.env` and asks you to fill in `SUPABASE_*`
and `ADZUNA_APP_ID` / `ADZUNA_APP_KEY`.

Flags:
- `./scripts/dev.sh --setup-only` — bootstrap without starting the server
- `./scripts/dev.sh --skip-install` — skip reinstalling deps

Migrations live in `alembic/versions/`; `alembic upgrade head` applies whatever
the database has not seen. That is the single source of truth for the schema.

## The API

```
GET  /api/v1/companies?flutter_only=true&ncr_or_remote=true&hiring_soon=false
GET  /api/v1/companies/{id}       # with the evidence behind the listing
POST /api/v1/companies            # service key only
GET  /api/v1/users/me
GET  /health
```

`/companies` is the product. The three query flags map exactly to the question:
proven Flutter stack, reachable from NCR or remote, and a leading signal in the
last 90 days.

## Collectors

```bash
python -m app.jobs.run_adzuna      # postings -> Flutter evidence + companies
python -m app.jobs.run_cleanup     # drop staffing firms, fix names, re-grade evidence
```

Adzuna is the only feed. All **57** companies in the current answer qualify
through it. `run_cleanup` is idempotent and safe to re-run.

Removed collectors, and why:
- `run_rss` — 33 funded companies, 0 overlap with the Flutter set; funding news
  cannot reveal a tech stack. Removing it also removed the last LLM call, so
  there is no `anthropic` dependency and no `ANTHROPIC_API_KEY`.
- `run_discovery` (GitHub Dart orgs) — 37 companies at 100% precision but **0**
  reached the answer; a GitHub org with no India-or-remote posting can never
  pass the location filter.
- the ATS stack (greenhouse / lever / ashby / smartrecruiters) — 7,793 postings,
  59 of them Flutter.

In production these run from `.github/workflows/scrape-*.yml`. Nothing needs to
run more often than daily: whether a company builds in Flutter does not change
by the hour.

**Required secrets in GitHub Actions:**
- `DATABASE_URL`
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
- `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`
- `RENDER_DEPLOY_HOOK` — optional, enables auto-deploy

## Layout

- `app/collectors/` — one module per source, all inheriting `BaseCollector`
- `app/jobs/` — standalone entry points for GitHub Actions
- `app/api/` — routers, aggregated in `app/api/router.py`
- `app/utils/job_parser.py` — tech, location and experience extraction
- `alembic/versions/` — migrations

## Tests

```bash
pytest
ruff check app/ tests/
```

## Deployment

Push to `main`; `deploy.yml` calls the Render deploy hook if
`RENDER_DEPLOY_HOOK` is set. See `render.yaml`.
