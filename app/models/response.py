from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class Price(BaseModel):
    value: float = Field(..., description="Valeur du prix")
    currency: Optional[str] = Field(None, description="Devise (€, $, £, CHF)")


class MenuItem(BaseModel):
    name: str = Field(..., description="Nom du plat")
    price: Price = Field(..., description="Prix du plat")
    description: str = Field(..., description="Description du plat")
    ingredients: List[str] = Field(default_factory=list, description="Liste des ingrédients")
    dietary: List[str] = Field(default_factory=list, description="Tags diététiques")


class MenuSection(BaseModel):
    name: str = Field(..., description="Nom de la section")
    items: List[MenuItem] = Field(default_factory=list, description="Items de la section")


class Menu(BaseModel):
    name: Optional[str] = Field(None, description="Nom du restaurant/menu")
    sections: List[MenuSection] = Field(default_factory=list, description="Sections du menu")


class MenuData(BaseModel):
    menu: Menu = Field(..., description="Menu structuré")


class ScanMenuResponse(BaseModel):
    success: bool = Field(..., description="Statut du traitement")
    message: str = Field(..., description="Message de statut")
    data: Optional[MenuData] = Field(None, description="Données du menu si succès")
    processing_time_seconds: float = Field(..., description="Temps de traitement en secondes")
    scan_id: str = Field(..., description="Identifiant unique du scan")
    timestamp: datetime = Field(default_factory=datetime.now, description="Horodatage")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Menu scanné avec succès",
                "data": {
                    "menu": {
                        "name": "Restaurant Example",
                        "sections": [
                            {
                                "name": "ENTRÉES",
                                "items": [
                                    {
                                        "name": "Salade César",
                                        "price": {"value": 12.50, "currency": "€"},
                                        "description": "Salade romaine, parmesan, croûtons",
                                        "ingredients": ["salade romaine", "parmesan", "croûtons"],
                                        "dietary": ["végétarien"]
                                    }
                                ]
                            }
                        ]
                    }
                },
                "processing_time_seconds": 3.45,
                "scan_id": "scan_123456789",
                "timestamp": "2025-01-01T12:00:00Z"
            }
        }


class ErrorResponse(BaseModel):
    success: bool = Field(default=False, description="Statut (toujours False pour erreur)")
    message: str = Field(..., description="Message d'erreur")
    error_code: Optional[str] = Field(None, description="Code d'erreur spécifique")
    details: Optional[Dict[str, Any]] = Field(None, description="Détails additionnels")
    timestamp: datetime = Field(default_factory=datetime.now, description="Horodatage")


class HealthResponse(BaseModel):
    status: str = Field(..., description="Statut de l'application")
    version: str = Field(..., description="Version de l'application")
    timestamp: datetime = Field(default_factory=datetime.now, description="Horodatage")
    services: Dict[str, str] = Field(default_factory=dict, description="Statut des services")