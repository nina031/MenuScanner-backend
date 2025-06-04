# app/services/ocr_service.py
import asyncio
import time
from typing import Dict, Any
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError
import structlog

from app.core.config import settings
from app.core.exceptions import OCRError

logger = structlog.get_logger()


class OCRService:
    """Service OCR avec Azure Document Intelligence."""
    
    def __init__(self):
        """Initialise le client Azure OCR."""
        try:
            self.client = DocumentAnalysisClient(
                endpoint=settings.azure_doc_intelligence_endpoint,
                credential=AzureKeyCredential(settings.azure_doc_intelligence_api_key)
            )
            logger.info("Client Azure OCR initialisé")
        except Exception as e:
            logger.error("Erreur lors de l'initialisation du client Azure OCR", error=str(e))
            raise OCRError(f"Impossible d'initialiser le client Azure OCR: {e}")
    
    async def extract_text_from_image(self, image_data: bytes) -> str:
        """
        Extrait le texte d'une image avec Azure Document Intelligence.
        
        Args:
            image_data: Données de l'image
            
        Returns:
            str: Texte extrait (pas un dict !)
        """
        start_time = time.time()
        
        try:
            logger.info("Début OCR", size_bytes=len(image_data))
            
            # Vérifier que le client existe
            if not hasattr(self, 'client') or self.client is None:
                raise OCRError("Client Azure OCR non initialisé")
            
            # OCR avec Azure
            poller = self.client.begin_analyze_document(
                model_id="prebuilt-read",
                document=image_data
            )
            
            result = await asyncio.get_event_loop().run_in_executor(
                None, poller.result
            )
            
            # Extraire juste le texte brut
            raw_text = ""
            for page in result.pages:
                for line in page.lines:
                    raw_text += line.content + "\n"
            
            processing_time = time.time() - start_time
            
            # Validation simple
            if len(raw_text.strip()) < 10:
                raise OCRError(
                    "Pas assez de texte extrait. Image illisible ?",
                    error_code="INSUFFICIENT_TEXT"
                )
            
            logger.info(
                "OCR terminé",
                text_length=len(raw_text),
                processing_time=processing_time
            )
            
            # RETOURNER JUSTE LA STRING, pas un dict
            return raw_text.strip()
            
        except HttpResponseError as e:
            if e.status_code == 401:
                raise OCRError("Clé API Azure invalide", error_code="AZURE_AUTH_ERROR")
            elif e.status_code == 429:
                raise OCRError("Limite Azure atteinte", error_code="AZURE_RATE_LIMIT")
            else:
                raise OCRError(f"Erreur Azure: {e.message}", error_code="AZURE_API_ERROR")
                
        except Exception as e:
            logger.error("Erreur OCR", error=str(e))
            raise OCRError(f"Erreur OCR: {e}")


# Instance globale du service
ocr_service = OCRService()