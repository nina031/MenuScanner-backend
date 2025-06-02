# app/api/endpoints/health.py
from fastapi import APIRouter, HTTPException
import structlog

from app.core.config import settings
from app.models.response import HealthResponse
from app.services.pipeline_service import pipeline_service

logger = structlog.get_logger()
router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Endpoint de vérification de santé de l'application.
    
    Vérifie:
    - Statut de l'application
    - Connexion au stockage R2
    - Azure Document Intelligence OCR
    - Claude LLM API
    """
    try:
        # Utiliser le health check du pipeline qui teste tous les services
        pipeline_health = await pipeline_service.health_check()
        
        # Déterminer le statut global
        global_status = pipeline_health["pipeline"]
        services_status = pipeline_health["services"]
        
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