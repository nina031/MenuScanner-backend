# app/api/router.py
from fastapi import APIRouter

from app.api.endpoints import health, scan

router = APIRouter()

# Inclure les endpoints
router.include_router(health.router, tags=["health"])
router.include_router(scan.router, tags=["scan"])