# app/models/request.py
from typing import Optional
from pydantic import BaseModel, Field


class ScanMenuRequest(BaseModel):
    """Modèle de requête pour le scan de menu."""
    
    # Le fichier sera géré via FastAPI UploadFile
    # Ce modèle peut être étendu pour des paramètres additionnels
    
    language_hint: Optional[str] = Field(
        default="fr", 
        description="Langue principale attendue du menu"
    )
    
    processing_options: Optional[dict] = Field(
        default_factory=dict,
        description="Options de traitement spécifiques"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "language_hint": "fr",
                "processing_options": {
                    "include_ingredients": True,
                    "include_dietary_tags": True
                }
            }
        }