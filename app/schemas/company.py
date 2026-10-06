from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CompanyBase(BaseModel):
    name: str
    domain: str | None = None
    careers_url: str | None = None
    ats_type: str | None = None
    ats_slug: str | None = None
    github_org: str | None = None
    app_package_id: str | None = None
    employee_count: int | None = None
    industry: str | None = None
    location: str | None = None
    website: str | None = None
    logo_url: str | None = None


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(BaseModel):
    name: str | None = None
    domain: str | None = None
    careers_url: str | None = None
    ats_type: str | None = None
    ats_slug: str | None = None
    github_org: str | None = None
    employee_count: int | None = None
    industry: str | None = None
    location: str | None = None
    website: str | None = None
    logo_url: str | None = None
    is_active: bool | None = None


class CompanyRead(CompanyBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CompanyScoreRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    intent_score: float
    stack_fingerprint: dict[str, Any] | None = None
    signal_count: int
    strongest_signal: str | None = None
    last_scored_at: datetime


class CompanyListItem(CompanyRead):
    score: CompanyScoreRead | None = None


class CompanyDetail(CompanyRead):
    score: CompanyScoreRead | None = None
    intent_signals: list["IntentSignalRead"] = Field(default_factory=list)
    stack_signals: list["StackSignalRead"] = Field(default_factory=list)


# Forward refs resolved after signal schemas import below
from app.schemas.signal import IntentSignalRead, StackSignalRead  # noqa: E402

CompanyDetail.model_rebuild()
