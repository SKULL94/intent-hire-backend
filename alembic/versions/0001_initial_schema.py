"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-06

Mirrors the SQL in hiresignal_backend.md including indexes and RLS policies.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgcrypto for gen_random_uuid()
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("domain", sa.Text, unique=True),
        sa.Column("careers_url", sa.Text),
        sa.Column("ats_type", sa.Text),
        sa.Column("ats_slug", sa.Text),
        sa.Column("github_org", sa.Text),
        sa.Column("app_package_id", sa.Text),
        sa.Column("employee_count", sa.Integer),
        sa.Column("industry", sa.Text),
        sa.Column("location", sa.Text),
        sa.Column("website", sa.Text),
        sa.Column("logo_url", sa.Text),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_companies_domain", "companies", ["domain"])
    op.create_index(
        "idx_companies_active", "companies", ["is_active"],
        postgresql_where=sa.text("is_active = true"),
    )
    op.create_index("idx_companies_ats", "companies", ["ats_type", "ats_slug"])

    op.create_table(
        "intent_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("signal_type", sa.Text, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("raw_data", postgresql.JSONB),
        sa.Column("extracted", postgresql.JSONB),
        sa.Column("confidence", sa.Float, server_default=sa.text("0.0")),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_signals_company", "intent_signals", ["company_id"])
    op.create_index("idx_signals_type", "intent_signals", ["signal_type"])
    op.create_index("idx_signals_detected", "intent_signals",
                    [sa.text("detected_at DESC")])

    op.create_table(
        "stack_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.Text, nullable=False),
        sa.Column("source_url", sa.Text),
        sa.Column("technologies", postgresql.JSONB, nullable=False),
        sa.Column("raw_evidence", sa.Text),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_stack_company", "stack_signals", ["company_id"])

    op.create_table(
        "company_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("companies.id", ondelete="CASCADE"),
                  unique=True, nullable=False),
        sa.Column("intent_score", sa.Float, server_default=sa.text("0.0")),
        sa.Column("stack_fingerprint", postgresql.JSONB),
        sa.Column("signal_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("strongest_signal", sa.Text),
        sa.Column("last_scored_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_scores_intent", "company_scores",
                    [sa.text("intent_score DESC")])

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("auth_id", postgresql.UUID(as_uuid=True), unique=True),
        sa.Column("email", sa.Text, unique=True, nullable=False),
        sa.Column("name", sa.Text),
        sa.Column("skills", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("experience_years", sa.Integer),
        sa.Column("preferred_locations", postgresql.JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("min_salary", sa.Integer),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("tech_fit", sa.Float, nullable=False),
        sa.Column("intent_score", sa.Float, nullable=False),
        sa.Column("top_signals", postgresql.JSONB),
        sa.Column("status", sa.Text, server_default=sa.text("'new'")),
        sa.Column("matched_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "company_id", name="uq_matches_user_company"),
    )
    op.create_index("idx_matches_user", "matches", ["user_id"])
    op.create_index("idx_matches_score", "matches", [sa.text("score DESC")])

    op.create_table(
        "validation_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("taken_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("top_n", sa.Integer, server_default=sa.text("20")),
        sa.Column("predictions", postgresql.JSONB, nullable=False),
        sa.Column("labeled_at", sa.DateTime(timezone=True)),
        sa.Column("labels", postgresql.JSONB),
        sa.Column("precision_at_10", sa.Float),
        sa.Column("precision_at_20", sa.Float),
    )

    # RLS — writes always go through the service key which bypasses RLS.
    for table in ("companies", "intent_signals", "stack_signals", "company_scores"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f'CREATE POLICY "authenticated read" ON {table} '
            f"FOR SELECT TO authenticated USING (true)"
        )

    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute(
        'CREATE POLICY "own user row" ON users '
        "FOR ALL TO authenticated USING (auth_id = auth.uid())"
    )

    op.execute("ALTER TABLE matches ENABLE ROW LEVEL SECURITY")
    op.execute(
        'CREATE POLICY "own matches" ON matches FOR ALL TO authenticated '
        "USING (user_id IN (SELECT id FROM users WHERE auth_id = auth.uid()))"
    )


def downgrade() -> None:
    for table in ("companies", "intent_signals", "stack_signals",
                  "company_scores", "users", "matches"):
        op.execute(f'DROP POLICY IF EXISTS "authenticated read" ON {table}')
        op.execute(f'DROP POLICY IF EXISTS "own user row" ON {table}')
        op.execute(f'DROP POLICY IF EXISTS "own matches" ON {table}')
    op.drop_table("validation_snapshots")
    op.drop_table("matches")
    op.drop_table("users")
    op.drop_table("company_scores")
    op.drop_table("stack_signals")
    op.drop_table("intent_signals")
    op.drop_table("companies")
