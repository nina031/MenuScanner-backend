# app/api/endpoints/websocket.py
import uuid
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional
import structlog
from datetime import datetime

from app.services.websocket_manager import websocket_manager
from app.services.pipeline_service import pipeline_service
from app.services.storage_service import storage_service
from app.utils.validators import validate_image_file
from app.core.exceptions import FileValidationError, StorageError

logger = structlog.get_logger()
router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Endpoint WebSocket principal pour les connexions en temps réel."""
    connection_id = f"conn_{uuid.uuid4().hex[:12]}"
    
    try:
        # Connecter le WebSocket
        await websocket_manager.connect(websocket, connection_id)
        
        logger.info("Nouvelle connexion WebSocket", connection_id=connection_id)
        
        # Boucle d'écoute pour les messages entrants (ping/pong, etc.)
        while True:
            try:
                # Recevoir les messages du client (optionnel)
                data = await websocket.receive_text()
                
                # Traiter les messages spéciaux si nécessaire
                if data == "ping":
                    await websocket_manager.send_to_connection(connection_id, {
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat()
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


@router.post("/upload-and-process")
async def upload_and_process_websocket(
    file: UploadFile = File(..., description="Image du menu à traiter"),
    connection_id: str = Form(..., description="ID de la connexion WebSocket"),
    language_hint: Optional[str] = Form(default="fr", description="Langue du menu"),
    cleanup_temp_file: Optional[bool] = Form(default=True, description="Nettoyer fichier temporaire")
):
    """
    Upload et traitement avec notifications WebSocket en temps réel.
    
    Ce endpoint :
    1. Valide et upload l'image
    2. Lance le traitement en arrière-plan
    3. Envoie les mises à jour via WebSocket
    """
    scan_id = f"scan_{uuid.uuid4().hex[:12]}"
    
    logger.info(
        "Début upload et traitement WebSocket",
        scan_id=scan_id,
        connection_id=connection_id,
        filename=file.filename
    )
    
    try:
        # Vérifier que la connexion WebSocket existe
        if not websocket_manager.is_connected(connection_id):
            raise HTTPException(
                status_code=400,
                detail={
                    "success": False,
                    "message": "Connexion WebSocket invalide ou fermée",
                    "error_code": "INVALID_WEBSOCKET_CONNECTION"
                }
            )
        
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
        
        logger.info(
            "Fichier uploadé, démarrage traitement WebSocket",
            scan_id=scan_id,
            file_key=file_key,
            connection_id=connection_id
        )
        
        # 5. Lancer le traitement en arrière-plan avec WebSocket
        processing_options = {
            "cleanup_temp_file": cleanup_temp_file
        }
        
        # Démarrer le traitement asynchrone
        asyncio.create_task(
            pipeline_service.process_menu_image_websocket(
                file_key=file_key,
                connection_id=connection_id,
                scan_id=scan_id,
                language_hint=language_hint,
                processing_options=processing_options
            )
        )
        
        # 6. Réponse immédiate confirmant le démarrage
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Traitement démarré avec succès",
                "data": {
                    "scan_id": scan_id,
                    "connection_id": connection_id,
                    "file_key": file_key,
                    "processing_status": "started"
                }
            }
        )
        
    except FileValidationError as e:
        logger.warning(
            "Validation fichier échouée WebSocket",
            scan_id=scan_id,
            connection_id=connection_id,
            error=str(e)
        )
        
        # Notifier l'erreur via WebSocket
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
        
        # Notifier l'erreur via WebSocket
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
        
        # Notifier l'erreur via WebSocket
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
    """Debug: Liste des connexions WebSocket actives."""
    return {
        "active_connections": websocket_manager.get_active_connections(),
        "connection_count": websocket_manager.get_connection_count()
    }


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