# app/services/pipeline_service.py
import time
import uuid
from typing import Optional, AsyncGenerator, Dict, Any
import structlog

from app.core.exceptions import PipelineError
from app.services.storage_service import storage_service
from app.services.ocr_service import ocr_service
from app.services.llm_service import llm_service

logger = structlog.get_logger()


class PipelineService:
    """Service orchestrant le pipeline complet de traitement des menus."""
    
    async def stream_menu_processing(self, file_key: str) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Traite une image de menu en streaming : OCR + LLM par sections.
        
        Args:
            file_key: Clé du fichier dans R2
            
        Yields:
            Dict: Messages de streaming du traitement
            
        Raises:
            PipelineError: Si le traitement échoue
        """
        pipeline_start = time.time()
        processing_id = f"pipeline_{uuid.uuid4().hex[:8]}"
        
        logger.info(
            "Début du pipeline de traitement en streaming",
            processing_id=processing_id,
            file_key=file_key
        )
        
        try:
            # Étape 1: Télécharger l'image depuis R2
            yield {
                "type": "status",
                "message": "Téléchargement de l'image...",
                "step": "download",
                "processing_id": processing_id
            }
            
            step1_start = time.time()
            image_data = await storage_service.download_temp_file(file_key)
            step1_duration = time.time() - step1_start
            
            logger.info(
                "Image téléchargée",
                processing_id=processing_id,
                duration_seconds=round(step1_duration, 2),
                image_size_bytes=len(image_data)
            )
            
            yield {
                "type": "step_complete",
                "step": "download",
                "duration_seconds": round(step1_duration, 2),
                "image_size_bytes": len(image_data)
            }
            
            # Étape 2: OCR avec Azure Document Intelligence
            yield {
                "type": "status",
                "message": "Extraction du texte (OCR)...",
                "step": "ocr"
            }
            
            step2_start = time.time()
            ocr_text = await ocr_service.extract_text_from_image(image_data)
            # DEBUG: Vérifier le type
            logger.info("Debug OCR", ocr_type=type(ocr_text), ocr_length=len(str(ocr_text)))

            if not isinstance(ocr_text, str):
                logger.error("OCR n'a pas retourné une string!", ocr_type=type(ocr_text))
                ocr_text = str(ocr_text)  # Conversion forcée
            step2_duration = time.time() - step2_start
            
            logger.info(
                "OCR terminé",
                processing_id=processing_id,
                duration_seconds=round(step2_duration, 2),
                text_length=len(ocr_text)
            )
            
            yield {
                "type": "step_complete",
                "step": "ocr",
                "duration_seconds": round(step2_duration, 2),
                "text_length": len(ocr_text)
            }
            
            # Étape 3: Traitement LLM par sections en streaming
            yield {
                "type": "status",
                "message": "Analyse du menu par l'IA...",
                "step": "llm_start"
            }
            
            # Streamer le traitement LLM
            async for llm_message in llm_service.stream_menu_processing(ocr_text):
                yield llm_message
            
            # Pipeline terminé
            total_duration = time.time() - pipeline_start
            
            logger.info(
                "Pipeline streaming terminé avec succès",
                processing_id=processing_id,
                total_duration_seconds=round(total_duration, 2)
            )
            
            yield {
                "type": "pipeline_complete",
                "processing_id": processing_id,
                "total_duration_seconds": round(total_duration, 2)
            }
            
        except Exception as e:
            total_duration = time.time() - pipeline_start
            
            logger.error(
                "Erreur dans le pipeline streaming",
                processing_id=processing_id,
                error=str(e),
                duration_seconds=round(total_duration, 2)
            )
            
            yield {
                "type": "error",
                "error": str(e),
                "processing_id": processing_id,
                "duration_seconds": round(total_duration, 2)
            }
            
            raise PipelineError(
                f"Erreur lors du traitement du menu: {str(e)}",
                error_code="PIPELINE_ERROR",
                details={
                    "processing_id": processing_id,
                    "file_key": file_key,
                    "duration_seconds": round(total_duration, 2)
                }
            )


# Instance globale du service
pipeline_service = PipelineService()