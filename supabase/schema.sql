-- =============================================================================
-- HireSignal — complete initial schema for Supabase (PostgreSQL 15)
--
-- Usage:
--   1. Open Supabase → SQL Editor → New Query
--   2. Paste this entire file
--   3. Click Run
--
-- Idempotent: uses CREATE ... IF NOT EXISTS everywhere, and drops existing
-- policies before re-creating. Safe to run more than once.
--
-- After running this, you can SKIP `alembic upgrade head` locally — stamp the
-- migration as applied so Alembic knows the DB is already at the right version:
--     alembic stamp head
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Extensions
-- -----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- =============================================================================
-- Tables
-- =============================================================================

-- companies ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS companies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    domain          TEXT UNIQUE,
    careers_url     TEXT,
    ats_type        TEXT,         -- 'greenhouse' | 'lever' | 'ashby' | 'workable' | 'smartrecruiters' | 'other'
    ats_slug        TEXT,
    github_org      TEXT,
    app_package_id  TEXT,         -- Phase 2
    employee_count  INTEGER,
    industry        TEXT,
    location        TEXT,
    website         TEXT,
    logo_url        TEXT,
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_companies_domain ON companies(domain);
CREATE INDEX IF NOT EXISTS idx_companies_active ON companies(is_active) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_companies_ats    ON companies(ats_type, ats_slug);

-- intent_signals -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS intent_signals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    signal_type     TEXT NOT NULL,  -- 'ats_job' | 'funding' | 'news' | 'hn_whos_hiring' | 'github_activity'
    source          TEXT NOT NULL,
    raw_data        JSONB,
    extracted       JSONB,
    confidence      REAL DEFAULT 0.0,
    detected_at     TIMESTAMPTZ DEFAULT now(),
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_signals_company   ON intent_signals(company_id);
CREATE INDEX IF NOT EXISTS idx_signals_type      ON intent_signals(signal_type);
CREATE INDEX IF NOT EXISTS idx_signals_detected  ON intent_signals(detected_at DESC);

-- stack_signals --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS stack_signals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    source_type     TEXT NOT NULL,  -- 'github' | 'ats_job_nlp' | 'wappalyzer' | 'blog' | 'hn_whos_hiring' | 'apk'
    source_url      TEXT,
    technologies    JSONB NOT NULL,
    raw_evidence    TEXT,
    detected_at     TIMESTAMPTZ DEFAULT now(),
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_stack_company ON stack_signals(company_id);

-- company_scores -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS company_scores (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id          UUID UNIQUE NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    intent_score        REAL DEFAULT 0.0,
    stack_fingerprint   JSONB,
    signal_count        INTEGER DEFAULT 0,
    strongest_signal    TEXT,
    last_scored_at      TIMESTAMPTZ DEFAULT now(),
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scores_intent ON company_scores(intent_score DESC);

-- users ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_id             UUID UNIQUE,                   -- Supabase Auth user ID (auth.uid())
    email               TEXT UNIQUE,                   -- null for phone-only (OTP) signups
    phone               TEXT UNIQUE,                   -- null for email signups
    name                TEXT,
    skills              JSONB NOT NULL DEFAULT '{}'::jsonb,
    experience_years    INTEGER,
    preferred_locations JSONB DEFAULT '[]'::jsonb,
    min_salary          INTEGER,                       -- monthly INR
    is_active           BOOLEAN DEFAULT true,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT ck_users_email_or_phone CHECK (email IS NOT NULL OR phone IS NOT NULL)
);

-- matches --------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS matches (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company_id      UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    score           REAL NOT NULL,
    tech_fit        REAL NOT NULL,
    intent_score    REAL NOT NULL,
    top_signals     JSONB,
    status          TEXT DEFAULT 'new',  -- 'new' | 'viewed' | 'saved' | 'applied' | 'dismissed'
    matched_at      TIMESTAMPTZ DEFAULT now(),
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_matches_user_company UNIQUE (user_id, company_id)
);

CREATE INDEX IF NOT EXISTS idx_matches_user  ON matches(user_id);
CREATE INDEX IF NOT EXISTS idx_matches_score ON matches(score DESC);

-- validation_snapshots -------------------------------------------------------
CREATE TABLE IF NOT EXISTS validation_snapshots (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    taken_at        TIMESTAMPTZ DEFAULT now(),
    top_n           INTEGER DEFAULT 20,
    predictions     JSONB NOT NULL,
    labeled_at      TIMESTAMPTZ,
    labels          JSONB,
    precision_at_10 REAL,
    precision_at_20 REAL
);

-- =============================================================================
-- Row Level Security
--
-- All writes happen through FastAPI with the service key, which bypasses RLS.
-- The policies below only govern reads from the authenticated Flutter client.
-- =============================================================================

-- Public-ish tables: readable by any authenticated user ----------------------
ALTER TABLE companies      ENABLE ROW LEVEL SECURITY;
ALTER TABLE intent_signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE stack_signals  ENABLE ROW LEVEL SECURITY;
ALTER TABLE company_scores ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "authenticated read" ON companies;
CREATE POLICY "authenticated read" ON companies
    FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "authenticated read" ON intent_signals;
CREATE POLICY "authenticated read" ON intent_signals
    FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "authenticated read" ON stack_signals;
CREATE POLICY "authenticated read" ON stack_signals
    FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "authenticated read" ON company_scores;
CREATE POLICY "authenticated read" ON company_scores
    FOR SELECT TO authenticated USING (true);

-- Per-user tables: only the owning user can see their row --------------------
ALTER TABLE users   ENABLE ROW LEVEL SECURITY;
ALTER TABLE matches ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "own user row" ON users;
CREATE POLICY "own user row" ON users
    FOR ALL TO authenticated USING (auth_id = auth.uid());

DROP POLICY IF EXISTS "own matches" ON matches;
CREATE POLICY "own matches" ON matches
    FOR ALL TO authenticated
    USING (user_id IN (SELECT id FROM users WHERE auth_id = auth.uid()));

-- =============================================================================
-- Done. Verify with:
--   SELECT table_name FROM information_schema.tables WHERE table_schema='public';
-- Expected: companies, intent_signals, stack_signals, company_scores,
--           users, matches, validation_snapshots
-- =============================================================================
