from fastapi import APIRouter

from app.api import admin, companies, health, users

api_router = APIRouter()

# Health lives at the root for Render health checks.
api_router.include_router(health.router)

v1 = APIRouter(prefix="/api/v1")
# The product is one question: which companies hire Flutter, and which are
# about to. `/companies` answers it; there is deliberately nothing else.
v1.include_router(companies.router)
v1.include_router(users.router)
v1.include_router(admin.router)

api_router.include_router(v1)
