from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.company_score import CompanyScore
    from app.models.intent_signal import IntentSignal
    from app.models.job import Job
    from app.models.stack_signal import StackSignal


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    domain: Mapped[str | None] = mapped_column(String, unique=True)
    careers_url: Mapped[str | None] = mapped_column(String)

    # 'greenhouse' | 'lever' | 'ashby' | 'workable' | 'smartrecruiters' | 'other'
    ats_type: Mapped[str | None] = mapped_column(String)
    ats_slug: Mapped[str | None] = mapped_column(String)

    github_org: Mapped[str | None] = mapped_column(String)
    app_package_id: Mapped[str | None] = mapped_column(String)  # Phase 2

    employee_count: Mapped[int | None] = mapped_column(Integer)
    industry: Mapped[str | None] = mapped_column(String)
    location: Mapped[str | None] = mapped_column(String)
    website: Mapped[str | None] = mapped_column(String)
    logo_url: Mapped[str | None] = mapped_column(String)

    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    intent_signals: Mapped[list["IntentSignal"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    stack_signals: Mapped[list["StackSignal"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    jobs: Mapped[list["Job"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    score: Mapped["CompanyScore | None"] = relationship(
        back_populates="company", cascade="all, delete-orphan", uselist=False
    )
