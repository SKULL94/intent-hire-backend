#!/usr/bin/env bash
# Local dev bootstrap — single-command setup + start.
#
# Usage:
#   ./scripts/dev.sh                # full bootstrap, then start uvicorn
#   ./scripts/dev.sh --setup-only   # bootstrap, don't start the server
#   ./scripts/dev.sh --skip-install # just run migrations + seed + start
#
# Idempotent. Safe to re-run.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

SETUP_ONLY=0
SKIP_INSTALL=0
for arg in "$@"; do
  case "$arg" in
    --setup-only)   SETUP_ONLY=1 ;;
    --skip-install) SKIP_INSTALL=1 ;;
    -h|--help)
      sed -n '2,10p' "$0"
      exit 0 ;;
    *)
      echo "unknown flag: $arg" >&2
      exit 2 ;;
  esac
done

say() { printf "\033[1;36m▶ %s\033[0m\n" "$*"; }
warn() { printf "\033[1;33m! %s\033[0m\n" "$*" >&2; }

# ─── 1. .env ──────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    warn ".env created from .env.example — fill in SUPABASE_* and ANTHROPIC_API_KEY, then re-run."
    exit 1
  else
    warn "No .env.example found; create .env yourself and re-run."
    exit 1
  fi
fi

# Export .env so python / alembic see it (strips comments, respects quotes).
set -a
# shellcheck disable=SC1091
source .env
set +a

# ─── 2. venv ──────────────────────────────────────────────────────────────────
if [ ! -d .venv ]; then
  say "Creating virtualenv in .venv"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# ─── 3. dependencies ──────────────────────────────────────────────────────────
if [ "$SKIP_INSTALL" -eq 0 ]; then
  say "Installing dependencies (requirements-dev.txt)"
  pip install --upgrade pip >/dev/null
  pip install -r requirements-dev.txt
fi

# ─── 4. database migrations ───────────────────────────────────────────────────
if [ -z "${DATABASE_URL:-}" ]; then
  warn "DATABASE_URL is not set in .env — can't run migrations. Fill it and re-run."
  exit 1
fi
say "Applying Alembic migrations (alembic upgrade head)"
alembic upgrade head

# ─── 5. seed companies ────────────────────────────────────────────────────────
say "Seeding companies (idempotent)"
python -m scripts.seed_companies

if [ "$SETUP_ONLY" -eq 1 ]; then
  say "Setup complete. Skipping server start (--setup-only)."
  exit 0
fi

# ─── 6. start the dev server ──────────────────────────────────────────────────
say "Starting FastAPI on http://localhost:8000  (Ctrl-C to stop)"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
