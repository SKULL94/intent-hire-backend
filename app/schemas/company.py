from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CompanyBase(BaseModel):
    name: str
    domain: str | None = None
    careers_url: str | None = None
    github_org: str | None = None
    play_store_dev_id: str | None = None
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
    github_org: str | None = None
    play_store_dev_id: str | None = None
    app_package_id: str | None = None
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


class FlutterEvidenceRead(BaseModel):
    """Why we believe this company builds in Flutter."""

    model_config = ConfigDict(from_attributes=True)

    source_type: str
    source_url: str | None = None
    technologies: dict[str, Any] | None = None
    raw_evidence: str | None = None
    detected_at: datetime


class HiringSignalRead(BaseModel):
    """Why we believe this company is about to hire."""

    model_config = ConfigDict(from_attributes=True)

    signal_type: str
    source: str
    confidence: float
    detected_at: datetime


class CompanyListItem(CompanyRead):
    pass


class CompanyDetail(CompanyRead):
    stack_signals: list[FlutterEvidenceRead] = Field(default_factory=list)
    intent_signals: list[HiringSignalRead] = Field(default_factory=list)
