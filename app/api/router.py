from fastapi import APIRouter

from app.api.endpoints import health, scan, websocket

router = APIRouter()

router.include_router(health.router, tags=["health"])
router.include_router(scan.router, tags=["scan"])
router.include_router(websocket.router, tags=["websocket"])