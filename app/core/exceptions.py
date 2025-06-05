from typing import Any, Dict, Optional


class MenuScannerException(Exception):
    
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
    pass


class StorageError(MenuScannerException):
    pass


class OCRError(MenuScannerException):
    pass


class LLMError(MenuScannerException):
    pass


class PipelineError(MenuScannerException):
    pass