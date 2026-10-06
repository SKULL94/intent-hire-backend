from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class IntentSignalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    signal_type: str
    source: str
    extracted: dict[str, Any] | None = None
    confidence: float
    detected_at: datetime
    expires_at: datetime | None = None


class StackSignalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    source_type: str
    source_url: str | None = None
    technologies: dict[str, float]
    detected_at: datetime


class RecentSignalItem(IntentSignalRead):
    company_name: str | None = None
    company_domain: str | None = None
