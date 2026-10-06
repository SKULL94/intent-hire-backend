from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserProfileUpdate(BaseModel):
    email: EmailStr | None = None
    name: str | None = None
    skills: dict[str, float] = Field(default_factory=dict)
    experience_years: int | None = None
    preferred_locations: list[str] = Field(default_factory=list)
    min_salary: int | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    auth_id: UUID | None = None
    email: str
    name: str | None = None
    skills: dict[str, float]
    experience_years: int | None = None
    preferred_locations: list[str]
    min_salary: int | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
