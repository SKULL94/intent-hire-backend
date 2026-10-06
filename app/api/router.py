from fastapi import APIRouter

from app.api import admin, companies, health, matches, signals, users

api_router = APIRouter()

# Health lives at the root for Render health checks.
api_router.include_router(health.router)

v1 = APIRouter(prefix="/api/v1")
v1.include_router(companies.router)
v1.include_router(signals.router)
v1.include_router(users.router)
v1.include_router(matches.router)
v1.include_router(admin.router)

api_router.include_router(v1)
