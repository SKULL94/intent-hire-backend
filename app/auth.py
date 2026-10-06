"""Supabase JWT verification dependency.

Supabase issues HS256-signed JWTs whose shared secret is the project's JWT secret
(the long value under Project Settings → API → JWT Secret). The Flutter client
sends the access token as `Authorization: Bearer <token>`; this module verifies
the signature + expiry and resolves the `auth.uid()` to the matching row in the
local `users` table.
"""
from __future__ import annotations

from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User

_bearer = HTTPBearer(auto_error=False)


def _decode_token(token: str) -> dict:
    """Decode a Supabase JWT. The service key is a signed JWT itself, so we reuse
    the project JWT secret via the SUPABASE_SERVICE_KEY env (same signing key).

    Supabase uses HS256 with the project JWT secret. For simplicity we skip
    verification only in development and when the key is not configured.
    """
    secret = settings.supabase_service_key or settings.supabase_anon_key
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase JWT secret not configured",
        )
    try:
        return jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from exc


def get_current_auth_id(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> UUID:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    payload = _decode_token(creds.credentials)
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing subject")
    try:
        return UUID(sub)
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid subject") from exc


def get_current_user(
    auth_id: UUID = Depends(get_current_auth_id),
    db: Session = Depends(get_db),
) -> User:
    user = db.query(User).filter(User.auth_id == auth_id).first()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User profile not found")
    return user


def require_service_key(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Admin endpoints: raw service key must be presented as a bearer token."""
    if not creds or creds.credentials != settings.supabase_service_key:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Service key required")
