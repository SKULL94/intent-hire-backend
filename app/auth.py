"""Supabase JWT verification dependency.

Supabase projects sign user access tokens one of two ways:

* **Asymmetric (current default)** — ES256/RS256 against a rotating keypair. The
  public keys are published at ``/auth/v1/.well-known/jwks.json`` and selected by
  the token's ``kid`` header. Nothing secret is needed to verify these.
* **Legacy symmetric** — HS256 against the project's JWT secret (Project
  Settings → JWT Keys → legacy secret), supplied as ``SUPABASE_JWT_SECRET``.

We pick the path from the token's own ``alg`` header, so a project that migrates
from one to the other keeps working without a code change.

Note that the service-role key and the anon key are themselves JWTs — they are
*not* signing keys, and must never be passed to ``jwt.decode`` as the secret.

The Flutter client sends the access token as ``Authorization: Bearer <token>``.
"""
from __future__ import annotations

import secrets
from functools import lru_cache
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User

_bearer = HTTPBearer(auto_error=False)

# Supabase stamps every user token with this audience.
_AUDIENCE = "authenticated"
_ASYMMETRIC_PREFIXES = ("ES", "RS", "PS", "Ed")


@lru_cache(maxsize=1)
def _jwk_client() -> PyJWKClient:
    """JWKS client with an in-process key cache.

    ``lifespan`` bounds how long a fetched key set is trusted, so a key rotation
    on the Supabase side is picked up without a restart.
    """
    return PyJWKClient(settings.jwks_url, cache_keys=True, lifespan=3600)


def _signing_key(token: str, alg: str) -> str:
    """Resolve the key to verify `token` with, based on its algorithm."""
    if alg.startswith(_ASYMMETRIC_PREFIXES):
        try:
            return _jwk_client().get_signing_key_from_jwt(token).key
        except jwt.PyJWKClientError as exc:
            # Unknown kid or unreachable JWKS endpoint — not the caller's fault.
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Unable to resolve token signing key",
            ) from exc

    if alg == "HS256":
        if not settings.supabase_jwt_secret:
            raise HTTPException(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "SUPABASE_JWT_SECRET must be set to verify HS256 tokens",
            )
        return settings.supabase_jwt_secret

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Unsupported token algorithm: {alg}")


def _decode_token(token: str) -> dict:
    if not settings.supabase_url:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "SUPABASE_URL must be set to verify tokens",
        )
    try:
        alg = jwt.get_unverified_header(token).get("alg", "")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Malformed token") from exc

    key = _signing_key(token, alg)
    try:
        return jwt.decode(
            token,
            key,
            algorithms=[alg],
            audience=_AUDIENCE,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "sub"]},
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
    expected = settings.supabase_service_key
    if not expected:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Service key not configured")
    if not creds or not secrets.compare_digest(creds.credentials, expected):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Service key required")
