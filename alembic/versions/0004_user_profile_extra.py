"""Add profile_extra JSONB column to users for bio, links, and highlights.

The cold-email composer needs recruiter-facing context that doesn't fit the
existing normalised columns: a human-readable experience label ("4.7+ years"),
current employer, location prose, social links, and hand-crafted bullet points.
A single JSONB bag is the lightest path — no new tables, no schema change for
every new field, and Pydantic's from_attributes picks it up via @property
accessors on the model.

Revision ID: 0004
Revises: 0003
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "profile_extra",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "profile_extra")
