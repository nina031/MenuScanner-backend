# app/main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog
import sys
import logging

from app.core.config import settings
from app.core.exceptions import MenuScannerException
from app.api.router import router as api_router

# Configuration du logging
logging.basicConfig(level=logging.DEBUG)  # Set the logging level

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer(colors=True)  # Couleurs pour plus de lisibilité
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True
)

logger = structlog.get_logger()


def create_app() -> FastAPI:
    """Crée l'application FastAPI."""
    
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="API Backend pour MenuScanner - Scan et analyse de menus avec IA",
        debug=settings.debug,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
    )
    
    # Middleware CORS pour le frontend React Native
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # À restreindre en production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Gestionnaire d'erreurs global pour nos exceptions custom
    @app.exception_handler(MenuScannerException)
    async def menu_scanner_exception_handler(request, exc: MenuScannerException):
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": exc.message,
                "error_code": exc.error_code,
                "details": exc.details
            }
        )
    
    # Inclure les routers API
    app.include_router(
        api_router,
        prefix="/api",
        responses={
            400: {"description": "Erreur de validation"},
            500: {"description": "Erreur interne du serveur"}
        }
    )
    
    # Route racine pour vérification rapide
    @app.get("/")
    async def root():
        return {
            "message": f"🍽️ {settings.app_name} v{settings.app_version}",
            "status": "running",
            "docs": "/docs" if settings.debug else "disabled"
        }
    
    logger.info(
        "Application FastAPI créée",
        app_name=settings.app_name,
        version=settings.app_version,
        debug=settings.debug
    )
    
    return app


# Créer l'instance de l'application
app = create_app()


if __name__ == "__main__":
    import uvicorn
    
    logger.info(
        "Démarrage du serveur",
        host=settings.host,
        port=settings.port,
        debug=settings.debug
    )
    
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info"
    )