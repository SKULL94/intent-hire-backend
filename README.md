# HireSignal — Backend

FastAPI service that collects hiring intent signals (ATS JSON APIs, RSS feeds,
GitHub, Hacker News, Wappalyzer), classifies them via the Claude API,
fingerprints company tech stacks, and serves personalized matches to the Flutter
mobile app. Database and auth are provided by Supabase; scraping schedules are
driven by GitHub Actions cron workflows.

The full architectural spec lives in [`hiresignal_backend.md`](./hiresignal_backend.md).

## Local setup — one command

```bash
./scripts/dev.sh
```

The script creates a `.venv`, installs `requirements-dev.txt`, applies Alembic
migrations, seeds companies, and starts the server on
<http://localhost:8000> (Swagger UI at `/docs`). On first run it copies
`.env.example` → `.env` and asks you to fill in `SUPABASE_*` and
`ANTHROPIC_API_KEY`.

Flags:
- `./scripts/dev.sh --setup-only` — bootstrap without starting the server
- `./scripts/dev.sh --skip-install` — re-run migrations/seed/server without reinstalling deps

### What's Alembic?

Alembic is a database migration tool. Instead of running SQL by hand,
`alembic/versions/*.py` files describe each schema change (create tables, add
columns, change indexes). `alembic upgrade head` applies every migration your
database hasn't seen yet. It's how we keep the Supabase schema in sync with the
SQLAlchemy models in `app/models/`.

The repo ships with migration `0001_initial_schema.py` which creates all 7
tables, their indexes, and the Row Level Security policies from the spec.

### Docker

```bash
docker compose up --build
```

## Running the collectors locally

Each collector is a standalone script invoked as a module.

```bash
python -m app.jobs.run_ats
python -m app.jobs.run_rss
python -m app.jobs.run_github
python -m app.jobs.run_hn
python -m app.jobs.run_wappalyzer
python -m app.jobs.run_scoring
python -m app.jobs.run_validation
```

In production these same scripts are triggered by the workflows in
`.github/workflows/scrape-*.yml` and `score.yml` / `validate.yml`.

## Discovering a company's ATS

```bash
python -m scripts.discover_ats <slug>
```

Probes Greenhouse / Lever / Ashby / Workable / SmartRecruiters endpoints for the
slug and reports which (if any) returns a 200.

## Deployment

Push to `main`; the `deploy.yml` workflow calls the Render deploy hook if
`RENDER_DEPLOY_HOOK` is configured. See `render.yaml` for the service definition.

**Required secrets in GitHub Actions:**
- `DATABASE_URL`
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
- `ANTHROPIC_API_KEY`
- `PAT_TOKEN` — personal token with `repo:read` for the GitHub collector
- `RENDER_DEPLOY_HOOK` — optional, enables auto-deploy

## Tests

```bash
pytest
```

## Project layout

See `hiresignal_backend.md` §Project Structure. In short:
- `app/collectors/` — one module per data source, all inheriting `BaseCollector`
- `app/processors/` — scoring, matching, Claude integration, stack fingerprinting
- `app/jobs/` — standalone entry points for GitHub Actions
- `app/api/` — FastAPI routers aggregated in `app/api/router.py`
- `alembic/` — migrations
- `.github/workflows/` — 8 cron workflows
