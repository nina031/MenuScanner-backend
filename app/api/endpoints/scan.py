# app/api/endpoints/scan.py
import uuid
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional
import structlog
import time
from datetime import datetime

from app.core.config import settings
from app.core.exceptions import FileValidationError, StorageError
from app.services.storage_service import storage_service
from app.utils.validators import validate_image_file

logger = structlog.get_logger()
router = APIRouter()


@router.post("/upload-image")
async def upload_menu_image(
    file: UploadFile = File(..., description="Image du menu à traiter")
):
    """
    Upload une image de menu vers le stockage R2.
    Endpoint legacy - utilisez WebSocket pour le traitement complet.
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
                "message": "Image uploadée avec succès - utilisez WebSocket pour le traitement",
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