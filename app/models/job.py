from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.company import Company


class Job(Base):
    """One job posting, kept as evidence rather than as a vacancy.

    The product does not ask "is there an opening" — it asks "does this company
    hire Flutter developers, and are they reachable from Delhi NCR". A posting
    answers both durably: its `technologies` prove the stack and its
    `location_normalized` proves the geography, and both stay true long after
    the role itself is filled.

    That is why nothing here expires on a short clock, and why `posted_at`
    being months old is not a reason to drop the row.
    """

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )

    # 'adzuna' — the feed this posting came from.
    source: Mapped[str] = mapped_column(String, nullable=False)
    # Identifier within that source. Unique per source, used to upsert rather
    # than duplicate a posting that is re-seen on every run.
    external_id: Mapped[str] = mapped_column(String, nullable=False)

    title: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str | None] = mapped_column(String)
    department: Mapped[str | None] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text)

    # Raw location string as published, plus a normalized form for filtering.
    # "Gurgaon, Haryana" and "Noida, Uttar Pradesh" are both `delhi_ncr`.
    location_raw: Mapped[str | None] = mapped_column(String)
    location_normalized: Mapped[str | None] = mapped_column(String)
    is_remote: Mapped[bool | None] = mapped_column()

    # Technology -> confidence, detected from title + description.
    technologies: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Minimum years of experience parsed from the description, when stated.
    min_years_experience: Mapped[int | None] = mapped_column(Integer)

    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)
    contract_time: Mapped[str | None] = mapped_column(String)

    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="jobs")
