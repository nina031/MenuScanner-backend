# app/api/endpoints/scan.py
import uuid
import json
import time
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
import structlog

from app.core.config import settings
from app.core.exceptions import FileValidationError, StorageError
from app.services.storage_service import storage_service
from app.services.pipeline_service import pipeline_service
from app.utils.validators import validate_image_file

logger = structlog.get_logger()
router = APIRouter()


@router.post("/upload-image")
async def upload_menu_image(
    file: UploadFile = File(..., description="Image du menu à traiter")
):
    """
    Upload une image de menu vers le stockage R2.
    
    Pour l'instant, cet endpoint :
    1. Valide le fichier image
    2. L'upload vers Cloudflare R2
    3. Retourne l'ID du fichier stocké
    
    Args:
        file: Fichier image (JPEG, PNG)
        
    Returns:
        JSON avec l'ID du fichier et les métadonnées
    """
    start_time = time.time()
    scan_id = f"scan_{uuid.uuid4().hex[:12]}"
    
    logger.info(
        "Début upload image",
        scan_id=scan_id,
        filename=file.filename,
        content_type=file.content_type
    )
    
    try:
        # 1. Validation du fichier
        await validate_image_file(file)
        
        # 2. Lire le contenu du fichier
        file_content = await file.read()
        
        # 3. Détecter l'extension
        file_extension = _get_file_extension(file.filename, file.content_type)
        
        # 4. Upload vers R2
        file_key = await storage_service.upload_temp_file(
            file_content=file_content,
            file_extension=file_extension,
            content_type=file.content_type
        )
        
        processing_time = time.time() - start_time
        
        logger.info(
            "Upload image réussi",
            scan_id=scan_id,
            file_key=file_key,
            file_size_bytes=len(file_content),
            processing_time=processing_time
        )
        
        # 5. Réponse de succès
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Image uploadée avec succès",
                "data": {
                    "scan_id": scan_id,
                    "file_key": file_key,
                    "file_size_bytes": len(file_content),
                    "content_type": file.content_type,
                    "original_filename": file.filename
                },
                "processing_time_seconds": round(processing_time, 3),
                "timestamp": datetime.utcnow().isoformat()
            }
        )
        
    except FileValidationError as e:
        logger.warning(
            "Validation fichier échouée",
            scan_id=scan_id,
            error=str(e),
            filename=file.filename
        )
        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "message": f"Fichier invalide: {e.message}",
                "error_code": e.error_code,
                "scan_id": scan_id
            }
        )
        
    except StorageError as e:
        logger.error(
            "Erreur stockage R2",
            scan_id=scan_id,
            error=str(e),
            error_code=getattr(e, 'error_code', None)
        )
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "message": "Erreur lors du stockage de l'image",
                "error_code": getattr(e, 'error_code', 'STORAGE_ERROR'),
                "scan_id": scan_id
            }
        )
        
    except Exception as e:
        logger.error(
            "Erreur inattendue upload",
            scan_id=scan_id,
            error=str(e),
            filename=file.filename
        )
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "message": "Erreur interne du serveur",
                "scan_id": scan_id
            }
        )


@router.get("/scan-menu/{file_key:path}")
async def scan_menu_processing(file_key: str):
    """
    Traite un menu en streaming à partir d'une image stockée dans R2.
    
    Cette route streame en temps réel :
    1. Le téléchargement de l'image
    2. L'extraction OCR 
    3. L'analyse de chaque section par l'IA
    
    Args:
        file_key: Clé du fichier dans R2
        
    Returns:
        Stream: Messages JSON en streaming
    """
    logger.info("🚀 Début traitement streaming pipeline réel", file_key=file_key)
    
    async def generate_stream():
        """Générateur pour le streaming des données du pipeline réel."""
        try:
            # Utiliser le vrai pipeline de traitement
            async for message in pipeline_service.stream_menu_processing(file_key):
                # Formater chaque message en JSON avec saut de ligne
                json_message = json.dumps(message, ensure_ascii=False)
                yield f"data: {json_message}\n\n"
                
        except Exception as e:
            logger.error("Erreur dans le pipeline streaming", error=str(e))
            # Envoyer l'erreur en format SSE
            error_message = {
                "type": "error",
                "error": str(e),
                "file_key": file_key
            }
            json_error = json.dumps(error_message, ensure_ascii=False)
            yield f"data: {json_error}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
        }
    )


@router.get("/test-simple")
async def test_simple():
    """Route de test ultra simple."""
    print("🔥 ROUTE TEST SIMPLE APPELÉE")
    return {"message": "Test simple fonctionne !"}


@router.get("/file/{file_key}")
async def get_uploaded_file(file_key: str):
    """
    Récupère un fichier uploadé depuis R2 (pour debug/test).
    
    Args:
        file_key: Clé du fichier dans R2
        
    Returns:
        Informations sur le fichier ou erreur si non trouvé
    """
    try:
        # Vérifier que le fichier existe (sans le télécharger)
        # Pour l'instant, on essaie juste de le télécharger
        file_content = await storage_service.download_temp_file(file_key)
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Fichier trouvé",
                "data": {
                    "file_key": file_key,
                    "size_bytes": len(file_content),
                    "exists": True
                }
            }
        )
        
    except StorageError as e:
        if getattr(e, 'error_code') == 'FILE_NOT_FOUND':
            raise HTTPException(
                status_code=404,
                detail={
                    "success": False,
                    "message": "Fichier non trouvé",
                    "error_code": "FILE_NOT_FOUND"
                }
            )
        else:
            raise HTTPException(
                status_code=500,
                detail={
                    "success": False,
                    "message": "Erreur lors de l'accès au fichier",
                    "error_code": getattr(e, 'error_code', 'STORAGE_ERROR')
                }
            )


@router.delete("/file/{file_key}")
async def delete_uploaded_file(file_key: str):
    """
    Supprime un fichier uploadé depuis R2.
    
    Args:
        file_key: Clé du fichier dans R2
        
    Returns:
        Confirmation de suppression
    """
    try:
        await storage_service.delete_temp_file(file_key)
        
        logger.info("Fichier supprimé manuellement", file_key=file_key)
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Fichier supprimé avec succès",
                "data": {
                    "file_key": file_key,
                    "deleted": True
                }
            }
        )
        
    except StorageError as e:
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "message": "Erreur lors de la suppression",
                "error_code": getattr(e, 'error_code', 'STORAGE_ERROR')
            }
        )


def _get_file_extension(filename: str, content_type: str) -> str:
    """
    Détermine l'extension du fichier.
    
    Args:
        filename: Nom du fichier original
        content_type: Type MIME
        
    Returns:
        Extension avec le point (ex: '.jpg')
    """
    # Essayer d'abord depuis le nom de fichier
    if filename and '.' in filename:
        return '.' + filename.split('.')[-1].lower()
    
    # Fallback sur le content-type
    content_type_map = {
        'image/jpeg': '.jpg',
        'image/jpg': '.jpg',
        'image/png': '.png',
        'image/webp': '.webp'
    }
    
    return content_type_map.get(content_type, '.jpg')

@router.post("/scan-menu-stream")
async def scan_menu_stream(
    file: UploadFile = File(..., description="Image du menu à traiter en streaming")
):
    """
    Upload + traitement streaming d'un menu en une seule requête.
    
    Cette route combine :
    1. Upload de l'image vers R2
    2. Traitement streaming (OCR + LLM par sections)
    
    Args:
        file: Fichier image (JPEG, PNG)
        
    Returns:
        Stream: Messages NDJSON en streaming
    """
    start_time = time.time()
    scan_id = f"scan_{uuid.uuid4().hex[:12]}"
    
    logger.info(
        "🚀 Début scan menu streaming",
        scan_id=scan_id,
        filename=file.filename,
        content_type=file.content_type
    )
    
    async def generate_stream():
        """Générateur pour le streaming upload + traitement."""
        try:
            # 1. Validation et upload
            yield json.dumps({
                "type": "status",
                "message": "Validation et upload de l'image...",
                "step": "upload",
                "scan_id": scan_id
            }) + "\n"
            
            # Validation du fichier
            await validate_image_file(file)
            
            # Lire le contenu du fichier
            file_content = await file.read()
            
            # Upload vers R2
            file_extension = _get_file_extension(file.filename, file.content_type)
            file_key = await storage_service.upload_temp_file(
                file_content=file_content,
                file_extension=file_extension,
                content_type=file.content_type
            )
            
            yield json.dumps({
                "type": "step_complete",
                "step": "upload",
                "file_key": file_key,
                "file_size_bytes": len(file_content)
            }) + "\n"
            
            # 2. Traitement streaming via le pipeline
            async for message in pipeline_service.stream_menu_processing(file_key):
                # Transformer les messages du pipeline pour le frontend
                if message["type"] == "section_complete":
                    # Message compatible avec votre frontend
                    yield json.dumps({
                        "type": "section",
                        "section": message["section"]
                    }) + "\n"
                elif message["type"] == "complete":
                    # Créer le menu final avec toutes les sections
                    # Note: vous devrez collecter toutes les sections pour créer le menu final
                    yield json.dumps({
                        "type": "complete",
                        "menu": {
                            "name": "Menu",  # Vous pouvez récupérer le vrai nom du menu_metadata
                            "sections": []   # Vous devrez collecter les sections
                        }
                    }) + "\n"
                elif message["type"] == "error":
                    # Erreur
                    yield json.dumps({
                        "type": "error",
                        "error": message["error"]
                    }) + "\n"
                else:
                    # Autres messages (status, etc.) - les passer tels quels
                    yield json.dumps(message) + "\n"
            
            # 3. Nettoyage optionnel du fichier temporaire
            try:
                await storage_service.delete_temp_file(file_key)
                logger.info("Fichier temporaire supprimé", file_key=file_key)
            except Exception as cleanup_error:
                logger.warning("Erreur nettoyage fichier", error=str(cleanup_error))
            
            total_time = time.time() - start_time
            logger.info(
                "Scan streaming terminé",
                scan_id=scan_id,
                total_time=total_time
            )
                
        except FileValidationError as e:
            error_msg = {
                "type": "error",
                "error": f"Fichier invalide: {e.message}",
                "error_code": e.error_code,
                "scan_id": scan_id
            }
            yield json.dumps(error_msg) + "\n"
            
        except StorageError as e:
            error_msg = {
                "type": "error", 
                "error": "Erreur de stockage",
                "error_code": getattr(e, 'error_code', 'STORAGE_ERROR'),
                "scan_id": scan_id
            }
            yield json.dumps(error_msg) + "\n"
            
        except Exception as e:
            logger.error("Erreur scan streaming", scan_id=scan_id, error=str(e))
            error_msg = {
                "type": "error",
                "error": str(e),
                "scan_id": scan_id
            }
            yield json.dumps(error_msg) + "\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
        }
    )