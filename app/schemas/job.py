from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JobCompanyRead(BaseModel):
    """Just enough company to render a job row without an N+1 fetch."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    domain: str | None = None
    logo_url: str | None = None
    careers_url: str | None = None


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    source: str
    title: str
    url: str | None = None
    department: str | None = None
    description: str | None = None

    location_raw: str | None = None
    location_normalized: str | None = None
    is_remote: bool | None = None

    technologies: dict[str, float] = {}
    min_years_experience: int | None = None

    salary_min: float | None = None
    salary_max: float | None = None
    contract_time: str | None = None

    posted_at: datetime | None = None
    last_seen_at: datetime

    company: JobCompanyRead

    # The employer's hiring-intent score, carried through so a job list can be
    # ranked by how strongly the company is hiring overall, not just by date.
    company_intent_score: float | None = None


class JobFacets(BaseModel):
    """Counts for the filters themselves, so the UI can show what is available
    rather than offering a filter that returns nothing."""

    total: int
    by_location: dict[str, int]
    by_technology: dict[str, int]
    remote: int
