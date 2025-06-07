import uuid
import asyncio
from datetime import datetime, timezone
from typing import Optional, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
import structlog

from app.services.websocket_manager import websocket_manager
from app.services.pipeline_service import pipeline_service
from app.services.storage_service import storage_service
from app.utils.validators import validate_image_file
from app.utils.file_utils import get_file_extension
from app.utils.response_utils import success_response
from app.core.exceptions import FileValidationError, StorageError

logger = structlog.get_logger()
router = APIRouter()

# Protection contre les traitements multiples
active_scans: Set[str] = set()
connection_scans: dict[str, str] = {}  # connection_id -> scan_id actuel


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    connection_id = f"conn_{uuid.uuid4().hex[:12]}"
    
    try:
        await websocket_manager.connect(websocket, connection_id)
        
        logger.info("Nouvelle connexion WebSocket", connection_id=connection_id)
        
        while True:
            try:
                data = await websocket.receive_text()
                
                if data == "ping":
                    await websocket_manager.send_to_connection(connection_id, {
                        "type": "pong",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    
            except WebSocketDisconnect:
                logger.info("WebSocket déconnecté", connection_id=connection_id)
                break
            except Exception as e:
                logger.error("Erreur traitement message WebSocket", 
                           connection_id=connection_id, error=str(e))
                break
                
    except WebSocketDisconnect:
        logger.info("WebSocket déconnecté pendant connexion", connection_id=connection_id)
    except Exception as e:
        logger.error("Erreur WebSocket", connection_id=connection_id, error=str(e))
    finally:
        websocket_manager.disconnect(connection_id)
        # Nettoyer les scans actifs pour cette connexion
        if connection_id in connection_scans:
            scan_id = connection_scans[connection_id]
            active_scans.discard(scan_id)
            del connection_scans[connection_id]
            logger.info("Scan nettoyé après déconnexion", connection_id=connection_id, scan_id=scan_id)


@router.post("/upload-and-process")
async def upload_and_process_websocket(
    file: UploadFile = File(..., description="Image du menu à traiter"),
    connection_id: str = Form(..., description="ID de la connexion WebSocket"),
    language_hint: Optional[str] = Form(default="fr", description="Langue du menu"),
    cleanup_temp_file: Optional[bool] = Form(default=True, description="Nettoyer fichier temporaire")
):
    scan_id = f"scan_{uuid.uuid4().hex[:12]}"
    
    logger.info(
        "Début upload et traitement WebSocket",
        scan_id=scan_id,
        connection_id=connection_id,
        filename=file.filename
    )
    
    try:
        if not websocket_manager.is_connected(connection_id):
            raise HTTPException(
                status_code=400,
                detail={
                    "success": False,
                    "message": "Connexion WebSocket invalide ou fermée",
                    "error_code": "INVALID_WEBSOCKET_CONNECTION"
                }
            )
        
        # Vérifier si cette connexion a déjà un scan en cours
        if connection_id in connection_scans:
            existing_scan_id = connection_scans[connection_id]
            logger.warning(
                "Tentative de double traitement détectée",
                connection_id=connection_id,
                existing_scan_id=existing_scan_id,
                new_scan_id=scan_id
            )
            raise HTTPException(
                status_code=409,
                detail={
                    "success": False,
                    "message": f"Un traitement est déjà en cours pour cette connexion (scan: {existing_scan_id})",
                    "error_code": "PROCESSING_ALREADY_IN_PROGRESS",
                    "existing_scan_id": existing_scan_id
                }
            )
        
        await validate_image_file(file)
        
        file_content = await file.read()
        
        file_extension = get_file_extension(file.filename, file.content_type)
        
        file_key = await storage_service.upload_temp_file(
            file_content=file_content,
            file_extension=file_extension,
            content_type=file.content_type
        )
        
        logger.info(
            "Fichier uploadé, démarrage traitement WebSocket",
            scan_id=scan_id,
            file_key=file_key,
            connection_id=connection_id
        )
        
        # Marquer le scan comme actif
        active_scans.add(scan_id)
        connection_scans[connection_id] = scan_id
        
        processing_options = {
            "cleanup_temp_file": cleanup_temp_file
        }
        
        # Créer une tâche avec cleanup automatique
        async def process_with_cleanup():
            try:
                await pipeline_service.process_menu_image_websocket(
                    file_key=file_key,
                    connection_id=connection_id,
                    scan_id=scan_id,
                    language_hint=language_hint,
                    processing_options=processing_options
                )
            finally:
                # Nettoyer les scans actifs
                active_scans.discard(scan_id)
                connection_scans.pop(connection_id, None)
                logger.info("Scan terminé et nettoyé", scan_id=scan_id, connection_id=connection_id)
        
        asyncio.create_task(process_with_cleanup())
        
        return success_response(
            "Traitement démarré avec succès",
            {
                "scan_id": scan_id,
                "connection_id": connection_id,
                "file_key": file_key,
                "processing_status": "started"
            }
        )
        
    except FileValidationError as e:
        logger.warning(
            "Validation fichier échouée WebSocket",
            scan_id=scan_id,
            connection_id=connection_id,
            error=str(e)
        )
        
        await websocket_manager.send_to_connection(connection_id, {
            "type": "error",
            "message": f"Fichier invalide: {e.message}",
            "scan_id": scan_id
        })
        
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
            "Erreur stockage WebSocket",
            scan_id=scan_id,
            connection_id=connection_id,
            error=str(e)
        )
        
        await websocket_manager.send_to_connection(connection_id, {
            "type": "error",
            "message": "Erreur lors du stockage de l'image",
            "scan_id": scan_id
        })
        
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
            "Erreur inattendue upload WebSocket",
            scan_id=scan_id,
            connection_id=connection_id,
            error=str(e)
        )
        
        await websocket_manager.send_to_connection(connection_id, {
            "type": "error",
            "message": "Erreur interne du serveur",
            "scan_id": scan_id
        })
        
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "message": "Erreur interne du serveur",
                "scan_id": scan_id
            }
        )


@router.get("/websocket/connections")
async def get_websocket_connections():
    return {
        "active_connections": websocket_manager.get_active_connections(),
        "connection_count": websocket_manager.get_connection_count()
    }


