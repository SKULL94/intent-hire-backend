"""Narrow the schema to one question: which companies hire Flutter.

The service used to rank companies by a decaying "intent score" and produce
per-user, per-job matches. That answered "is there an opening right now",
which every job board already answers, and answered it worse.

The product is now a company registry: who builds in Flutter, who is reachable
from Delhi NCR or remote, and who is about to hire. Nothing here needs a score,
a per-user match, or a prediction-accuracy snapshot, so those three tables go.

`companies.ats_type` / `ats_slug` go with them — ATS board polling was removed
(7,793 postings collected, 59 of them Flutter), and `play_store_dev_id` replaces
them as the handle that matters: a Play Store developer id is the entry point
for APK inspection, which proves a Flutter stack outright.

Postings, hiring signals and stack evidence are kept. They are the evidence base.

Revision ID: 0005
Revises: 0004
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # RLS policies must go before the tables they are attached to.
    op.execute('DROP POLICY IF EXISTS "own matches" ON matches')
    op.execute('DROP POLICY IF EXISTS "authenticated read" ON company_scores')

    op.drop_table("validation_snapshots")
    op.drop_table("matches")
    op.drop_table("company_scores")

    op.drop_index("idx_companies_ats", table_name="companies")
    op.drop_column("companies", "ats_type")
    op.drop_column("companies", "ats_slug")

    op.add_column("companies", sa.Column("play_store_dev_id", sa.Text, nullable=True))
    op.create_index(
        "idx_companies_play_store_dev",
        "companies",
        ["play_store_dev_id"],
        postgresql_where=sa.text("play_store_dev_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_companies_play_store_dev", table_name="companies")
    op.drop_column("companies", "play_store_dev_id")

    op.add_column("companies", sa.Column("ats_type", sa.Text, nullable=True))
    op.add_column("companies", sa.Column("ats_slug", sa.Text, nullable=True))
    op.create_index("idx_companies_ats", "companies", ["ats_type", "ats_slug"])

    op.create_table(
        "company_scores",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("intent_score", sa.Float, server_default=sa.text("0.0")),
        sa.Column("stack_fingerprint", postgresql.JSONB),
        sa.Column("signal_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("strongest_signal", sa.Text),
        sa.Column(
            "last_scored_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
    )
    op.create_index(
        "idx_scores_intent", "company_scores", [sa.text("intent_score DESC")]
    )

    op.create_table(
        "matches",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("taken_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("top_n", sa.Integer, server_default=sa.text("20")),
        sa.Column("predictions", postgresql.JSONB, nullable=False),
        sa.Column("labeled_at", sa.DateTime(timezone=True)),
        sa.Column("labels", postgresql.JSONB),
        sa.Column("precision_at_10", sa.Float),
        sa.Column("precision_at_20", sa.Float),
    )

    op.execute("ALTER TABLE company_scores ENABLE ROW LEVEL SECURITY")
    op.execute(
        'CREATE POLICY "authenticated read" ON company_scores '
        "FOR SELECT TO authenticated USING (true)"
    )
    op.execute("ALTER TABLE matches ENABLE ROW LEVEL SECURITY")
    op.execute(
        'CREATE POLICY "own matches" ON matches FOR ALL TO authenticated '
        "USING (user_id IN (SELECT id FROM users WHERE auth_id = auth.uid()))"
    )
