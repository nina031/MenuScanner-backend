from fastapi.responses import JSONResponse


def success_response(message: str, data: dict = None, status_code: int = 200) -> JSONResponse:
    """Crée une réponse de succès standardisée."""
    content = {
        "success": True,
        "message": message
    }
    if data:
        content["data"] = data
    return JSONResponse(status_code=status_code, content=content)


def error_response(message: str, error_code: str = None, details: dict = None, status_code: int = 400) -> JSONResponse:
    """Crée une réponse d'erreur standardisée."""
    content = {
        "success": False,
        "message": message
    }
    if error_code:
        content["error_code"] = error_code
    if details:
        content["details"] = details
    return JSONResponse(status_code=status_code, content=content)