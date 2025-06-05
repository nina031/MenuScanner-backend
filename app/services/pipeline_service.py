import time
import asyncio
from typing import Dict, Any, Optional
import structlog

from app.core.exceptions import PipelineError
from app.models.response import MenuData, ScanMenuResponse
from app.services.storage_service import storage_service
from app.services.ocr_service import ocr_service
from app.services.llm_service import llm_service
from app.services.websocket_manager import websocket_manager

logger = structlog.get_logger()


class PipelineService:
   """Service d'orchestration du pipeline OCR + LLM."""
   
   async def process_menu_image(
       self,
       file_key: str,
       scan_id: str,
       language_hint: str = "fr",
       processing_options: Optional[Dict[str, Any]] = None
   ) -> ScanMenuResponse:
       """
       Pipeline complet: téléchargement → OCR → LLM → structuration.
       
       Args:
           file_key: Clé du fichier dans R2
           scan_id: ID unique du scan
           language_hint: Langue principale du menu
           processing_options: Options de traitement
           
       Returns:
           ScanMenuResponse: Réponse complète avec menu structuré
           
       Raises:
           PipelineError: Si une étape du pipeline échoue
       """
       start_time = time.time()
       processing_options = processing_options or {}
       
       logger.info(
           "Début pipeline traitement menu",
           scan_id=scan_id,
           file_key=file_key,
           language=language_hint,
           options=processing_options
       )
       
       try:
           # 1. Télécharger l'image depuis R2
           logger.info("Étape 1/3: Téléchargement image depuis R2", scan_id=scan_id)
           image_data = await self._download_image(file_key, scan_id)
           
           # 2. Extraction OCR
           logger.info("Étape 2/3: Extraction OCR", scan_id=scan_id)
           ocr_result = await self._extract_text(image_data, scan_id)
           
           # 3. Structuration LLM
           logger.info("Étape 3/3: Structuration LLM", scan_id=scan_id)
           menu_data = await self._structure_menu(
               ocr_result["raw_text"], 
               language_hint, 
               scan_id
           )
           
           # 4. Construire la réponse finale
           total_processing_time = time.time() - start_time
           
           response = ScanMenuResponse(
               success=True,
               message="Menu scanné et structuré avec succès",
               data=menu_data,
               processing_time_seconds=round(total_processing_time, 3),
               scan_id=scan_id
           )
           
           # Récupérer la confiance OCR de manière sécurisée
           ocr_confidence = ocr_result.get("metadata", {}).get("confidence_scores", {}).get("average_line_confidence", 0.0)
           
           logger.info(
               "Pipeline terminé avec succès",
               scan_id=scan_id,
               sections_count=len(menu_data.menu.sections),
               total_items=sum(len(section.items) for section in menu_data.menu.sections),
               total_time=total_processing_time,
               ocr_time=ocr_result["metadata"]["processing_time_seconds"],
               ocr_confidence=ocr_confidence
           )
           
           # 5. Nettoyer le fichier temporaire (optionnel)
           if processing_options.get("cleanup_temp_file", True):
               try:
                   await storage_service.delete_temp_file(file_key)
                   logger.info("Fichier temporaire supprimé", scan_id=scan_id, file_key=file_key)
               except Exception as e:
                   logger.warning(
                       "Impossible de supprimer le fichier temporaire",
                       scan_id=scan_id,
                       file_key=file_key,
                       error=str(e)
                   )
           
           return response
           
       except Exception as e:
           total_processing_time = time.time() - start_time
           
           logger.error(
               "Erreur dans le pipeline",
               scan_id=scan_id,
               file_key=file_key,
               error=str(e),
               processing_time=total_processing_time
           )
           
           # Retourner une réponse d'erreur structurée
           return ScanMenuResponse(
               success=False,
               message=f"Erreur lors du traitement: {str(e)}",
               data=None,
               processing_time_seconds=round(total_processing_time, 3),
               scan_id=scan_id
           )

   async def process_menu_image_websocket(
       self,
       file_key: str,
       connection_id: str,
       scan_id: str,
       language_hint: str = "fr",
       processing_options: Optional[Dict[str, Any]] = None
   ) -> None:
       """
       Pipeline complet avec envoi WebSocket en temps réel.
       
       Args:
           file_key: Clé du fichier dans R2
           connection_id: ID de la connexion WebSocket
           scan_id: ID unique du scan
           language_hint: Langue principale du menu
           processing_options: Options de traitement
       """
       start_time = time.time()
       processing_options = processing_options or {}
       
       logger.info(
           "Début pipeline WebSocket traitement menu",
           scan_id=scan_id,
           connection_id=connection_id,
           file_key=file_key,
           language=language_hint
       )
       
       try:
           # Message de démarrage
           await websocket_manager.send_to_connection(connection_id, {
               "type": "processing_started",
               "message": "Traitement démarré",
               "scan_id": scan_id
           })
           
           # 1. Télécharger l'image depuis R2
           await websocket_manager.send_to_connection(connection_id, {
               "type": "progress",
               "step": "download",
               "message": "Téléchargement de l'image...",
               "scan_id": scan_id
           })
           
           image_data = await self._download_image(file_key, scan_id)
           
           # 2. Extraction OCR
           await websocket_manager.send_to_connection(connection_id, {
               "type": "progress",
               "step": "ocr",
               "message": "Extraction du texte...",
               "scan_id": scan_id
           })
           
           ocr_result = await self._extract_text(image_data, scan_id)
           
           # 3. Traitement sections avec WebSocket temps réel
           await self.process_menu_sections_websocket(
               raw_text=ocr_result["raw_text"],
               connection_id=connection_id,
               scan_id=scan_id,
               language_hint=language_hint
           )
           
           # 4. Nettoyage optionnel
           if processing_options.get("cleanup_temp_file", True):
               try:
                   await storage_service.delete_temp_file(file_key)
                   logger.info("Fichier temporaire supprimé", scan_id=scan_id)
               except Exception as e:
                   logger.warning("Impossible de supprimer le fichier temporaire", 
                                scan_id=scan_id, error=str(e))
           
           # 5. Message de fin
           total_processing_time = time.time() - start_time
           
           await websocket_manager.send_to_connection(connection_id, {
               "type": "complete",
               "message": "Menu entièrement analysé",
               "processing_time_seconds": round(total_processing_time, 3),
               "scan_id": scan_id
           }, flush=True)
           
           logger.info(
               "Pipeline WebSocket terminé",
               scan_id=scan_id,
               connection_id=connection_id,
               sections_count=3,  # À adapter selon vos données
               total_time=total_processing_time
           )
           
       except Exception as e:
           total_processing_time = time.time() - start_time
           
           logger.error(
               "Erreur dans le pipeline WebSocket",
               scan_id=scan_id,
               connection_id=connection_id,
               error=str(e),
               processing_time=total_processing_time
           )
           
           # Envoyer l'erreur via WebSocket
           await websocket_manager.send_to_connection(connection_id, {
               "type": "error",
               "message": f"Erreur lors du traitement: {str(e)}",
               "scan_id": scan_id
           })

   async def process_menu_sections_websocket(
       self,
       raw_text: str,
       connection_id: str,
       scan_id: str,
       language_hint: str = "fr"
   ) -> None:
       """Traite les sections une par une avec envoi WebSocket temps réel."""
       
       try:
           # 1. Détecter les sections
           await websocket_manager.send_to_connection(connection_id, {
               "type": "progress",
               "step": "sections_detection", 
               "message": "Détection des sections du menu...",
               "scan_id": scan_id
           })
           
           sections_info = await llm_service.detect_sections_and_title(raw_text)
           menu_title = sections_info.get("menu_title", "Menu")
           section_names = sections_info.get("sections", [])
           
           # Envoyer les sections détectées
           await websocket_manager.send_to_connection(connection_id, {
               "type": "sections_detected",
               "menu_title": menu_title,
               "sections": section_names,
               "scan_id": scan_id
           })
           
           # 2. Extraire le contenu des sections
           await websocket_manager.send_to_connection(connection_id, {
               "type": "progress",
               "step": "sections_extraction",
               "message": "Extraction du contenu des sections...",
               "scan_id": scan_id
           })
           
           sections_content = llm_service.extract_sections_content(raw_text, section_names)
           
           # 3. Analyser chaque section individuellement avec envoi immédiat
           for i, section_name in enumerate(section_names, 1):
               section_content = sections_content.get(section_name, "")
               
               logger.info(f"Début analyse section {section_name}", scan_id=scan_id)
               
               # Message de progression
               await websocket_manager.send_to_connection(connection_id, {
                   "type": "progress",
                   "step": "section_analysis",
                   "message": f"Analyse de la section {section_name}...",
                   "section_name": section_name,
                   "current_section": i,
                   "total_sections": len(section_names),
                   "scan_id": scan_id
               })
               
               # Analyser la section
               start_time = time.time()
               analyzed_section = await llm_service.analyze_single_section(
                   section_content, section_name, language_hint
               )
               processing_time = time.time() - start_time
               
               logger.info(
                   f"Section {section_name} analysée en {processing_time:.2f}s", 
                   scan_id=scan_id,
                   items_count=len(analyzed_section.items)
               )
               
               # ENVOI IMMÉDIAT de la section avec FLUSH
               await self.send_section_immediate(
                   connection_id=connection_id,
                   section=analyzed_section,
                   current=i,
                   total=len(section_names),
                   scan_id=scan_id
               )
               
               # Petite pause pour garantir l'ordre
               await asyncio.sleep(0.01)  # 10ms
               
       except Exception as e:
           logger.error(f"Erreur traitement sections WebSocket: {e}", scan_id=scan_id)
           raise

   async def send_section_immediate(
       self, 
       connection_id: str, 
       section, 
       current: int, 
       total: int, 
       scan_id: str
   ):
       """Envoie immédiatement une section via WebSocket avec flush forcé."""
       try:
           # Convertir la section en dict pour JSON
           section_dict = {
               "name": section.name,
               "items": [
                   {
                       "name": item.name,
                       "price": {
                           "value": item.price.value,
                           "currency": item.price.currency
                       },
                       "description": item.description,
                       "ingredients": item.ingredients,
                       "dietary": item.dietary
                   }
                   for item in section.items
               ]
           }
           
           message = {
               "type": "section_complete",
               "section": section_dict,
               "current_section": current,
               "total_sections": total,
               "scan_id": scan_id
           }
           
           # ENVOI IMMÉDIAT avec flush forcé
           await websocket_manager.send_to_connection(
               connection_id, 
               message, 
               flush=True
           )
           
           logger.info(
               f"Section {section.name} envoyée via WebSocket",
               scan_id=scan_id,
               connection_id=connection_id
           )
           
       except Exception as e:
           logger.error(f"Erreur envoi section WebSocket: {e}", scan_id=scan_id)
   
   async def _download_image(self, file_key: str, scan_id: str) -> bytes:
       """
       Télécharge l'image depuis R2.
       
       Args:
           file_key: Clé du fichier
           scan_id: ID du scan
           
       Returns:
           bytes: Données de l'image
           
       Raises:
           PipelineError: Si le téléchargement échoue
       """
       try:
           image_data = await storage_service.download_temp_file(file_key)
           
           logger.info(
               "Image téléchargée avec succès",
               scan_id=scan_id,
               file_key=file_key,
               size_bytes=len(image_data)
           )
           
           return image_data
           
       except Exception as e:
           logger.error(
               "Erreur téléchargement image",
               scan_id=scan_id,
               file_key=file_key,
               error=str(e)
           )
           raise PipelineError(
               f"Impossible de télécharger l'image: {e}",
               error_code="DOWNLOAD_FAILED"
           )
   
   async def _extract_text(self, image_data: bytes, scan_id: str) -> Dict[str, Any]:
       """
       Extrait le texte via OCR.
       
       Args:
           image_data: Données de l'image
           scan_id: ID du scan
           
       Returns:
           Dict: Résultat de l'OCR avec métadonnées
           
       Raises:
           PipelineError: Si l'OCR échoue
       """
       try:
           ocr_result = await ocr_service.extract_text_from_image(image_data)
           
           # Vérifier la qualité de l'OCR
           self._validate_ocr_quality(ocr_result, scan_id)
           
           return ocr_result
           
       except Exception as e:
           logger.error(
               "Erreur extraction OCR",
               scan_id=scan_id,
               error=str(e)
           )
           raise PipelineError(
               f"Erreur lors de l'extraction OCR: {e}",
               error_code="OCR_FAILED"
           )
   
   async def _structure_menu(self, raw_text: str, language_hint: str, scan_id: str) -> MenuData:
       """
       Structure le texte en menu via LLM.
       
       Args:
           raw_text: Texte brut de l'OCR
           language_hint: Langue du menu
           scan_id: ID du scan
           
       Returns:
           MenuData: Menu structuré
           
       Raises:
           PipelineError: Si la structuration échoue
       """
       try:
           menu_data = await llm_service.structure_menu_text(raw_text, language_hint)
           
           # Vérifier la qualité de la structuration
           self._validate_menu_quality(menu_data, scan_id)
           
           return menu_data
           
       except Exception as e:
           logger.error(
               "Erreur structuration LLM",
               scan_id=scan_id,
               error=str(e)
           )
           raise PipelineError(
               f"Erreur lors de la structuration LLM: {e}",
               error_code="LLM_FAILED"
           )
   
   def _validate_ocr_quality(self, ocr_result: Dict[str, Any], scan_id: str) -> None:
       """
       Valide la qualité du résultat OCR.
       
       Args:
           ocr_result: Résultat de l'OCR
           scan_id: ID du scan
           
       Raises:
           PipelineError: Si la qualité est insuffisante
       """
       raw_text = ocr_result.get("raw_text", "")
       metadata = ocr_result.get("metadata", {})
       confidence_scores = metadata.get("confidence_scores", {})
       
       # Vérifier que du texte a été extrait
       if not raw_text or len(raw_text.strip()) < 10:
           logger.warning(
               "Peu ou pas de texte extrait",
               scan_id=scan_id,
               text_length=len(raw_text)
           )
           raise PipelineError(
               "Impossible d'extraire suffisamment de texte de l'image. "
               "Vérifiez que l'image est lisible et contient du texte.",
               error_code="INSUFFICIENT_TEXT"
           )
       
       # Vérifier la confiance OCR (si disponible)
       avg_confidence = confidence_scores.get("average_line_confidence", 0.0)
       if avg_confidence > 0 and avg_confidence < 0.3:  # Seuil minimal de confiance
           logger.warning(
               "Confiance OCR faible",
               scan_id=scan_id,
               confidence=avg_confidence
           )
           # Ne pas bloquer, mais loguer l'avertissement
       
       # Récupérer le nombre de lignes de manière sécurisée
       lines_count = len(ocr_result.get("structured_data", {}).get("lines", []))
       
       logger.info(
           "Validation OCR réussie",
           scan_id=scan_id,
           text_length=len(raw_text),
           lines_count=lines_count,
           avg_confidence=avg_confidence
       )
   
   def _validate_menu_quality(self, menu_data: MenuData, scan_id: str) -> None:
       """
       Valide la qualité du menu structuré.
       
       Args:
           menu_data: Menu structuré
           scan_id: ID du scan
           
       Raises:
           PipelineError: Si la qualité est insuffisante
       """
       sections = menu_data.menu.sections
       total_items = sum(len(section.items) for section in sections)
       
       # Vérifier qu'il y a des items
       if total_items == 0:
           raise PipelineError(
               "Aucun plat détecté dans le menu. "
               "Vérifiez que l'image contient bien un menu lisible.",
               error_code="NO_MENU_ITEMS"
           )
       
       # Vérifier qu'il y a au moins une section
       if len(sections) == 0:
           raise PipelineError(
               "Aucune section détectée dans le menu.",
               error_code="NO_MENU_SECTIONS"
           )
       
       # Statistiques de qualité
       items_with_prices = sum(
           1 for section in sections 
           for item in section.items 
           if item.price.value > 0
       )
       
       items_with_descriptions = sum(
           1 for section in sections 
           for item in section.items 
           if item.description and len(item.description.strip()) > 5
       )
       
       price_coverage = items_with_prices / total_items if total_items > 0 else 0
       description_coverage = items_with_descriptions / total_items if total_items > 0 else 0
       
       # Avertissements de qualité (non bloquants)
       if price_coverage < 0.5:
           logger.warning(
               "Peu de prix détectés",
               scan_id=scan_id,
               price_coverage=price_coverage
           )
       
       if description_coverage < 0.3:
           logger.warning(
               "Peu de descriptions détectées",
               scan_id=scan_id,
               description_coverage=description_coverage
           )
       
       logger.info(
           "Validation menu réussie",
           scan_id=scan_id,
           sections_count=len(sections),
           total_items=total_items,
           price_coverage=price_coverage,
           description_coverage=description_coverage,
           restaurant_name=menu_data.menu.name
       )
   
   async def get_processing_status(self, scan_id: str) -> Dict[str, Any]:
       """
       Récupère le statut de traitement d'un scan.
       (Pour l'instant, le traitement est synchrone, mais cette méthode
       peut être étendue pour un traitement asynchrone)
       
       Args:
           scan_id: ID du scan
           
       Returns:
           Dict: Statut du traitement
       """
       # Pour l'instant, retour simple
       # À étendre si traitement asynchrone implémenté
       return {
           "scan_id": scan_id,
           "status": "completed",  # ou "processing", "failed"
           "message": "Traitement synchrone - voir résultat direct"
       }
   
   async def health_check(self) -> Dict[str, Any]:
       """
       Vérifie la santé de tous les services du pipeline.
       
       Returns:
           Dict: Statut de santé des services
       """
       health_status = {
           "pipeline": "healthy",
           "services": {}
       }
       
       # Test storage
       try:
           storage_healthy = await storage_service.check_connection()
           health_status["services"]["storage"] = "healthy" if storage_healthy else "unhealthy"
       except Exception as e:
           health_status["services"]["storage"] = "error"
           logger.error("Erreur health check storage", error=str(e))
       
       # Test OCR
       try:
           ocr_healthy = await ocr_service.check_connection()
           health_status["services"]["ocr"] = "healthy" if ocr_healthy else "unhealthy"
       except Exception as e:
           health_status["services"]["ocr"] = "error"
           logger.error("Erreur health check OCR", error=str(e))
       
       # Test LLM
       try:
           llm_healthy = await llm_service.check_connection()
           health_status["services"]["llm"] = "healthy" if llm_healthy else "unhealthy"
       except Exception as e:
           health_status["services"]["llm"] = "error"
           logger.error("Erreur health check LLM", error=str(e))
       
       # Test WebSocket Manager
       try:
           websocket_status = {
               "active_connections": websocket_manager.get_connection_count(),
               "status": "healthy"
           }
           health_status["services"]["websocket"] = "healthy"
       except Exception as e:
           health_status["services"]["websocket"] = "error"
           logger.error("Erreur health check WebSocket", error=str(e))
       
       # Déterminer le statut global
       all_services_healthy = all(
           status == "healthy" 
           for status in health_status["services"].values()
       )
       
       if not all_services_healthy:
           health_status["pipeline"] = "degraded"
       
       logger.info("Health check pipeline terminé", status=health_status)
       return health_status


# Instance globale du service
pipeline_service = PipelineService()