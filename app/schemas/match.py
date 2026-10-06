from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.company import CompanyRead, CompanyScoreRead

MatchStatus = Literal["new", "viewed", "saved", "applied", "dismissed"]


class MatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    company_id: UUID
    score: float
    tech_fit: float
    intent_score: float
    top_signals: list[dict[str, Any]] | None = None
    status: MatchStatus
    matched_at: datetime


class MatchWithCompany(MatchRead):
    company: CompanyRead
    company_score: CompanyScoreRead | None = None


class MatchStatusUpdate(BaseModel):
    status: MatchStatus
