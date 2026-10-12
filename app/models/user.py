from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.match import Match


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    auth_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), unique=True)
    # Phone + OTP signup yields a user with no email, and vice versa. A check
    # constraint (ck_users_email_or_phone) requires at least one of the two.
    email: Mapped[str | None] = mapped_column(String, unique=True)
    phone: Mapped[str | None] = mapped_column(String, unique=True)
    name: Mapped[str | None] = mapped_column(String)

    skills: Mapped[dict[str, float]] = mapped_column(
        JSONB, nullable=False, server_default="{}", default=dict
    )
    experience_years: Mapped[int | None] = mapped_column(Integer)
    preferred_locations: Mapped[list[str]] = mapped_column(
        JSONB, server_default="[]", default=list
    )
    min_salary: Mapped[int | None] = mapped_column(Integer)  # monthly INR

    profile_extra: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}", default=dict
    )

    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    matches: Mapped[list["Match"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def linkedin_url(self) -> str | None:
        return (self.profile_extra or {}).get("linkedin_url")

    @property
    def github_url(self) -> str | None:
        return (self.profile_extra or {}).get("github_url")

    @property
    def portfolio_url(self) -> str | None:
        return (self.profile_extra or {}).get("portfolio_url")

    @property
    def location_text(self) -> str | None:
        return (self.profile_extra or {}).get("location_text")

    @property
    def current_employer(self) -> str | None:
        return (self.profile_extra or {}).get("current_employer")

    @property
    def highlights(self) -> list[str]:
        return (self.profile_extra or {}).get("highlights") or []

    @property
    def experience_label(self) -> str | None:
        return (self.profile_extra or {}).get("experience_label")
