# app/services/ocr_service.py
import asyncio
from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import HttpResponseError
from typing import Dict, Any
import structlog
import time

from app.core.config import settings
from app.core.exceptions import OCRError

logger = structlog.get_logger()


class OCRService:
    """Service OCR simplifié - juste extraction de texte."""
    
    def __init__(self):
        try:
            self.client = DocumentAnalysisClient(
                endpoint=settings.azure_doc_intelligence_endpoint,
                credential=AzureKeyCredential(settings.azure_doc_intelligence_api_key)
            )
            logger.info("Client Azure OCR initialisé")
        except Exception as e:
            raise OCRError(f"Impossible d'initialiser Azure OCR: {e}")
    
    async def extract_text_from_image(self, image_data: bytes) -> Dict[str, Any]:
        """Extrait le texte d'une image avec Azure Document Intelligence."""
        start_time = time.time()
        
        try:
            logger.info("Début OCR", size_bytes=len(image_data))
            
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
            
            return {
                "raw_text": raw_text.strip(),
                "metadata": {
                    "processing_time_seconds": round(processing_time, 3),
                    "page_count": len(result.pages)
                }
            }
            
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
    
    async def check_connection(self) -> bool:
        """Test de connexion simple."""
        try:
            # Image test 1x1 pixel
            test_image = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\nIDAT\x08\x1dc\xf8\x00\x00\x00\x01\x00\x01\xab\xb4\x1b\xc6\x00\x00\x00\x00IEND\xaeB`\x82'
            
            poller = self.client.begin_analyze_document(
                model_id="prebuilt-read",
                document=test_image
            )
            
            await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, poller.result),
                timeout=30.0
            )
            
            return True
            
        except Exception as e:
            logger.error("Test connexion Azure failed", error=str(e))
            return False


# Instance globale
ocr_service = OCRService()