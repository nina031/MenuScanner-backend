# app/core/exceptions.py
from typing import Any, Dict, Optional


class MenuScannerException(Exception):
    """Exception de base pour MenuScanner."""
    
    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(self.message)


class FileValidationError(MenuScannerException):
    """Erreur de validation de fichier."""
    pass


class StorageError(MenuScannerException):
    """Erreur de stockage cloud."""
    pass


class OCRError(MenuScannerException):
    """Erreur de traitement OCR."""
    pass


class LLMError(MenuScannerException):
    """Erreur de traitement LLM."""
    pass


class PipelineError(MenuScannerException):
    """Erreur du pipeline de traitement."""
    pass