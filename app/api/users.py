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

    if user is None:
        if not payload.email:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email required on profile creation")
        user = User(
            auth_id=auth_id,
            email=payload.email,
            name=payload.name,
            skills=payload.skills,
            experience_years=payload.experience_years,
            preferred_locations=payload.preferred_locations,
            min_salary=payload.min_salary,
        )
        db.add(user)
    else:
        data = payload.model_dump(exclude_unset=True)
        for key, value in data.items():
            setattr(user, key, value)

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
