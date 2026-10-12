from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import get_current_auth_id
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserProfileUpdate, UserRead

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/profile", response_model=UserRead)
def upsert_profile(
    payload: UserProfileUpdate,
    auth_id: UUID = Depends(get_current_auth_id),
    db: Session = Depends(get_db),
) -> User:
    user = db.query(User).filter(User.auth_id == auth_id).first()

    _extra_fields = {
        "linkedin_url",
        "github_url",
        "portfolio_url",
        "location_text",
        "current_employer",
        "highlights",
        "experience_label",
    }

    if user is None:
        # Email-OTP signups carry an email, phone-OTP signups carry a phone.
        # Either identifies the user; requiring both would lock out phone users.
        if not payload.email and not payload.phone:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Either email or phone is required on profile creation",
            )
        extra: dict = {
            f: getattr(payload, f)
            for f in _extra_fields
            if getattr(payload, f, None) not in (None, [], "")
        }
        user = User(
            auth_id=auth_id,
            email=payload.email,
            phone=payload.phone,
            name=payload.name,
            skills=payload.skills,
            experience_years=payload.experience_years,
            preferred_locations=payload.preferred_locations,
            min_salary=payload.min_salary,
            profile_extra=extra,
        )
        db.add(user)
    else:
        data = payload.model_dump(exclude_unset=True)
        direct = {k: v for k, v in data.items() if k not in _extra_fields}
        for key, value in direct.items():
            setattr(user, key, value)

        new_extra = {
            f: getattr(payload, f)
            for f in _extra_fields
            if f in data and getattr(payload, f, None) not in (None, [], "")
        }
        if new_extra:
            user.profile_extra = {**(user.profile_extra or {}), **new_extra}

    db.commit()
    db.refresh(user)
    return user


@router.get("/me", response_model=UserRead)
def get_me(
    auth_id: UUID = Depends(get_current_auth_id),
    db: Session = Depends(get_db),
) -> User:
    user = db.query(User).filter(User.auth_id == auth_id).first()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profile not found")
    return user
