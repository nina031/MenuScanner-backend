from fastapi import UploadFile
from PIL import Image
import io
import structlog

from app.core.config import settings
from app.core.exceptions import FileValidationError

logger = structlog.get_logger()


async def validate_image_file(file: UploadFile) -> None:
    """
    Valide qu'un fichier uploadé est une image valide.
    
    Vérifications :
    - Type MIME autorisé
    - Taille du fichier
    - Que le fichier est bien une image (via PIL)
    - Dimensions minimales/maximales
    
    Args:
        file: Fichier uploadé via FastAPI
        
    Raises:
        FileValidationError: Si le fichier ne passe pas la validation
    """
    
    # 1. Vérifier le type MIME
    if file.content_type not in settings.allowed_file_types_list:
        raise FileValidationError(
            f"Type de fichier non autorisé: {file.content_type}. "
            f"Types autorisés: {', '.join(settings.allowed_file_types_list)}",
            error_code="INVALID_FILE_TYPE"
        )
    
    # 2. Lire le contenu pour les vérifications
    file_content = await file.read()
    
    # 3. Vérifier la taille
    file_size = len(file_content)
    if file_size > settings.max_file_size_bytes:
        raise FileValidationError(
            f"Fichier trop volumineux: {file_size} bytes. "
            f"Taille max: {settings.max_file_size_mb}MB",
            error_code="FILE_TOO_LARGE"
        )
    
    if file_size == 0:
        raise FileValidationError(
            "Fichier vide",
            error_code="EMPTY_FILE"
        )
    
    # 4. Vérifier que c'est bien une image avec PIL
    try:
        image = Image.open(io.BytesIO(file_content))
        
        # Vérifier les dimensions
        width, height = image.size
        
        # Dimensions minimales (pour éviter les images trop petites)
        min_width, min_height = 100, 100
        if width < min_width or height < min_height:
            raise FileValidationError(
                f"Image trop petite: {width}x{height}px. "
                f"Minimum: {min_width}x{min_height}px",
                error_code="IMAGE_TOO_SMALL"
            )
        
        # Dimensions maximales (pour éviter les images énormes)
        max_width, max_height = 5000, 5000  # Augmenté pour les photos modernes
        if width > max_width or height > max_height:
            raise FileValidationError(
                f"Image trop grande: {width}x{height}px. "
                f"Maximum: {max_width}x{max_height}px",
                error_code="IMAGE_TOO_LARGE"
            )
        
        # Vérifier le format d'image
        if image.format not in ['JPEG', 'PNG', 'WEBP']:
            raise FileValidationError(
                f"Format d'image non supporté: {image.format}",
                error_code="UNSUPPORTED_IMAGE_FORMAT"
            )
        
        logger.info(
            "Validation image réussie",
            filename=file.filename,
            size_bytes=file_size,
            dimensions=f"{width}x{height}",
            format=image.format
        )
        
    except Exception as e:
        if isinstance(e, FileValidationError):
            raise
        else:
            raise FileValidationError(
                f"Fichier corrompu ou format invalide: {str(e)}",
                error_code="INVALID_IMAGE_FILE"
            )
    
    finally:
        # Remettre le curseur au début pour les prochaines lectures
        await file.seek(0)