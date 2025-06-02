# app/core/config.py
import os
from typing import List
from pydantic_settings import BaseSettings
from pydantic import Field
from dotenv import load_dotenv
import logging

# Forcer le rechargement du .env (important pour le développement)
load_dotenv(override=True)

# Configuration du logging détaillé
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)

# Logger pour l'application
logger = logging.getLogger("menuscanner")
logger.setLevel(logging.DEBUG)


class Settings(BaseSettings):
    """Configuration de l'application."""
    
    # Application
    app_name: str = Field(default="MenuScanner Backend")
    app_version: str = Field(default="1.0.0")
    debug: bool = Field(default=False)
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    
    # Cloudflare R2 Storage
    cloudflare_account_id: str = Field(..., description="Cloudflare Account ID")
    cloudflare_access_key_id: str = Field(..., description="Cloudflare R2 Access Key ID")
    cloudflare_secret_access_key: str = Field(..., description="Cloudflare R2 Secret Access Key")
    cloudflare_bucket_name: str = Field(default="menuscanner-temp")
    cloudflare_endpoint_url: str = Field(..., description="Cloudflare R2 Endpoint URL")
    
    # Azure Document Intelligence
    azure_doc_intelligence_endpoint: str = Field(..., description="Azure Document Intelligence Endpoint")
    azure_doc_intelligence_api_key: str = Field(..., description="Azure Document Intelligence API Key")
    
    # Claude API
    claude_api_key: str = Field(..., description="Claude API Key")
    
    # Configuration fichiers
    max_file_size_mb: int = Field(default=10, description="Taille max fichier en MB")
    allowed_file_types: str = Field(default="image/jpeg,image/png,image/jpg")
    temp_file_retention_hours: int = Field(default=24, description="Durée de rétention fichiers temporaires")
    
    @property
    def allowed_file_types_list(self) -> List[str]:
        """Retourne la liste des types de fichiers autorisés."""
        return [ft.strip() for ft in self.allowed_file_types.split(",")]
    
    @property
    def max_file_size_bytes(self) -> int:
        """Retourne la taille max en bytes."""
        return self.max_file_size_mb * 1024 * 1024

    class Config:
        env_file = ".env"
        case_sensitive = False


# Instance globale des settings
settings = Settings()