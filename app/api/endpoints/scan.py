import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, UploadFile, File, HTTPException
import structlog
import time

from app.core.config import settings
from app.utils.file_utils import get_file_extension
from app.utils.response_utils import success_response
from app.core.exceptions import FileValidationError, StorageError
from app.services.storage_service import storage_service
from app.utils.validators import validate_image_file

logger = structlog.get_logger()
router = APIRouter()


@router.post("/upload-image")
async def upload_menu_image(
    file: UploadFile = File(..., description="Image du menu à traiter")
):
    start_time = time.time()
    scan_id = f"scan_{uuid.uuid4().hex[:12]}"
    
    logger.info(
        "Début upload image",
        scan_id=scan_id,
        filename=file.filename,
        content_type=file.content_type
    )
    
    try:
        await validate_image_file(file)
        
        file_content = await file.read()
        
        file_extension = get_file_extension(file.filename, file.content_type)
        
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
        
        return success_response(
            "Image uploadée avec succès - utilisez WebSocket pour le traitement",
            {
                "scan_id": scan_id,
                "file_key": file_key,
                "file_size_bytes": len(file_content),
                "content_type": file.content_type,
                "original_filename": file.filename,
                "processing_time_seconds": round(processing_time, 3),
                "timestamp": datetime.now(timezone.utc).isoformat()
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


