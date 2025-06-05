from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog
import logging

from app.core.config import settings
from app.core.exceptions import MenuScannerException
from app.api.router import router as api_router
from app.api.endpoints.websocket import router as websocket_router

logging.basicConfig(level=logging.DEBUG)

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer(colors=True)
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True
)

logger = structlog.get_logger()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="API Backend pour MenuScanner - Scan et analyse de menus avec IA",
        debug=settings.debug,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
    )
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"]
    )
    
    @app.exception_handler(MenuScannerException)
    async def menu_scanner_exception_handler(_, exc: MenuScannerException):
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": exc.message,
                "error_code": exc.error_code,
                "details": exc.details
            }
        )
    
    app.include_router(
        api_router,
        prefix="/api",
        responses={
            400: {"description": "Erreur de validation"},
            500: {"description": "Erreur interne du serveur"}
        }
    )
    app.include_router(
        websocket_router,
        prefix="/api",
        tags=["websocket"]
    )
    
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