# app/api/endpoints/health.py
from fastapi import APIRouter, HTTPException
import structlog

from app.core.config import settings
from app.models.response import HealthResponse
from app.services.storage_service import storage_service

logger = structlog.get_logger()
router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Endpoint de vérification de santé de l'application.
    
    Vérifie:
    - Statut de l'application
    - Connexion au stockage R2
    - Autres services (à ajouter)
    """
    try:
        services_status = {}
        
        # Vérifier la connexion R2 avec timeout plus long
        try:
            import asyncio
            r2_connected = await asyncio.wait_for(
                storage_service.check_connection(), 
                timeout=10.0  # 10 secondes max
            )
            services_status["storage_r2"] = "healthy" if r2_connected else "unhealthy"
        except asyncio.TimeoutError:
            logger.error("Timeout lors du check R2")
            services_status["storage_r2"] = "timeout"
        except Exception as e:
            logger.error("Erreur lors du check R2", error=str(e))
            services_status["storage_r2"] = "error"
        
        # TODO: Ajouter vérifications pour Azure Document Intelligence et Claude API
        # services_status["azure_ocr"] = "not_checked"
        # services_status["claude_llm"] = "not_checked"
        
        # Déterminer le statut global
        all_healthy = all(status == "healthy" for status in services_status.values())
        global_status = "healthy" if all_healthy else "degraded"
        
        logger.info("Health check effectué", status=global_status, services=services_status)
        
        return HealthResponse(
            status=global_status,
            version=settings.app_version,
            services=services_status
        )
        
    except Exception as e:
        logger.error("Erreur lors du health check", error=str(e))
        raise HTTPException(
            status_code=500,
            detail="Erreur lors de la vérification de santé"
        )