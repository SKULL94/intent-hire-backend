"""Add users.phone and relax users.email for phone-only signup.

The Flutter client supports phone + OTP sign-in (Supabase Auth), which produces
an authenticated user with a phone number and no email address. The initial
schema made `email` NOT NULL, so those users could not be persisted.

This revision was already applied by hand to the hosted database; it is
committed here so the repo's migration history matches the deployed schema and
`alembic upgrade head` is reproducible on a fresh database.

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("phone", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_users_phone", "users", ["phone"])
    op.alter_column("users", "email", existing_type=sa.Text(), nullable=True)
    # At least one contact identifier must be present.
    op.create_check_constraint(
        "ck_users_email_or_phone",
        "users",
        "email IS NOT NULL OR phone IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_email_or_phone", "users", type_="check")
    # Rows created via phone-only signup have no email and cannot satisfy the
    # restored NOT NULL; drop them so the downgrade can complete.
    op.execute("DELETE FROM users WHERE email IS NULL")
    op.alter_column("users", "email", existing_type=sa.Text(), nullable=False)
    op.drop_constraint("uq_users_phone", "users", type_="unique")
    op.drop_column("users", "phone")
