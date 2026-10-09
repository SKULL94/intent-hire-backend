"""Add the jobs table: one row per posting instead of a per-company count.

The pipeline previously summarized a whole job board into
`intent_signals.raw_data = {"job_count": N}` and threw away the title,
location, URL and posting date that every ATS adapter already returned. That
made any per-role question — "Flutter roles in Delhi NCR needing 3+ years" —
unanswerable regardless of what the client offered.

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text()),
        sa.Column("department", sa.Text()),
        sa.Column("description", sa.Text()),
        sa.Column("location_raw", sa.Text()),
        sa.Column("location_normalized", sa.Text()),
        sa.Column("is_remote", sa.Boolean()),
        sa.Column("technologies", postgresql.JSONB()),
        sa.Column("min_years_experience", sa.Integer()),
        sa.Column("salary_min", sa.Float()),
        sa.Column("salary_max", sa.Float()),
        sa.Column("contract_time", sa.Text()),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # Collectors re-see the same posting on every run; this is what lets them
    # upsert `last_seen_at` instead of inserting a duplicate.
    op.create_unique_constraint(
        "uq_jobs_source_external_id", "jobs", ["source", "external_id"]
    )

    op.create_index("idx_jobs_company", "jobs", ["company_id"])
    op.create_index("idx_jobs_location", "jobs", ["location_normalized"])
    op.create_index("idx_jobs_posted", "jobs", ["posted_at"], postgresql_using="btree")
    # The core query is "which jobs mention flutter", which is a JSONB key
    # lookup — GIN is the index type that makes `technologies ? 'flutter'` fast.
    op.create_index(
        "idx_jobs_technologies", "jobs", ["technologies"], postgresql_using="gin"
    )


def downgrade() -> None:
    op.drop_index("idx_jobs_technologies", table_name="jobs")
    op.drop_index("idx_jobs_posted", table_name="jobs")
    op.drop_index("idx_jobs_location", table_name="jobs")
    op.drop_index("idx_jobs_company", table_name="jobs")
    op.drop_constraint("uq_jobs_source_external_id", "jobs", type_="unique")
    op.drop_table("jobs")
