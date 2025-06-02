# app/services/storage_service.py
import uuid
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from typing import Optional, BinaryIO
from datetime import datetime, timedelta
import structlog

from app.core.config import settings
from app.core.exceptions import StorageError

logger = structlog.get_logger()


class StorageService:
    """Service de gestion du stockage Cloudflare R2."""
    
    def __init__(self):
        """Initialise le client R2."""
        try:
            self.client = boto3.client(
                's3',
                endpoint_url=settings.cloudflare_endpoint_url,
                aws_access_key_id=settings.cloudflare_access_key_id,
                aws_secret_access_key=settings.cloudflare_secret_access_key,
                region_name='auto'  # R2 utilise 'auto' comme région
            )
            self.bucket_name = settings.cloudflare_bucket_name
            logger.info("Client R2 initialisé avec succès")
        except Exception as e:
            logger.error("Erreur lors de l'initialisation du client R2", error=str(e))
            raise StorageError(f"Impossible d'initialiser le client R2: {e}")
    
    async def upload_temp_file(
        self, 
        file_content: BinaryIO, 
        file_extension: str,
        content_type: Optional[str] = None
    ) -> str:
        """
        Upload un fichier temporaire dans R2.
        
        Args:
            file_content: Contenu du fichier
            file_extension: Extension du fichier (ex: '.jpg')
            content_type: Type MIME du fichier
            
        Returns:
            str: Clé unique du fichier uploadé
            
        Raises:
            StorageError: Si l'upload échoue
        """
        try:
            # Générer une clé unique pour le fichier
            file_key = self._generate_temp_file_key(file_extension)
            
            # Métadonnées pour le fichier
            metadata = {
                'upload_timestamp': datetime.utcnow().isoformat(),
                'retention_hours': str(settings.temp_file_retention_hours),
                'scanner_version': settings.app_version
            }
            
            # Paramètres d'upload
            upload_params = {
                'Bucket': self.bucket_name,
                'Key': file_key,
                'Body': file_content,
                'Metadata': metadata
            }
            
            # Ajouter le content-type si fourni
            if content_type:
                upload_params['ContentType'] = content_type
            
            # Upload le fichier
            self.client.put_object(**upload_params)
            
            logger.info(
                "Fichier temporaire uploadé avec succès",
                file_key=file_key,
                content_type=content_type
            )
            
            return file_key
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            logger.error(
                "Erreur client lors de l'upload", 
                error_code=error_code,
                error_message=str(e)
            )
            raise StorageError(
                f"Erreur lors de l'upload du fichier: {error_code}",
                error_code=error_code
            )
        except Exception as e:
            logger.error("Erreur inattendue lors de l'upload", error=str(e))
            raise StorageError(f"Erreur inattendue lors de l'upload: {e}")
    
    async def download_temp_file(self, file_key: str) -> bytes:
        """
        Télécharge un fichier temporaire depuis R2.
        
        Args:
            file_key: Clé du fichier à télécharger
            
        Returns:
            bytes: Contenu du fichier
            
        Raises:
            StorageError: Si le téléchargement échoue
        """
        try:
            response = self.client.get_object(
                Bucket=self.bucket_name,
                Key=file_key
            )
            
            content = response['Body'].read()
            
            logger.info(
                "Fichier temporaire téléchargé avec succès",
                file_key=file_key,
                size_bytes=len(content)
            )
            
            return content
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'NoSuchKey':
                logger.warning("Fichier non trouvé", file_key=file_key)
                raise StorageError(
                    f"Fichier non trouvé: {file_key}",
                    error_code="FILE_NOT_FOUND"
                )
            else:
                logger.error(
                    "Erreur client lors du téléchargement",
                    error_code=error_code,
                    file_key=file_key
                )
                raise StorageError(
                    f"Erreur lors du téléchargement: {error_code}",
                    error_code=error_code
                )
        except Exception as e:
            logger.error(
                "Erreur inattendue lors du téléchargement",
                error=str(e),
                file_key=file_key
            )
            raise StorageError(f"Erreur inattendue lors du téléchargement: {e}")
    
    async def delete_temp_file(self, file_key: str) -> bool:
        """
        Supprime un fichier temporaire de R2.
        
        Args:
            file_key: Clé du fichier à supprimer
            
        Returns:
            bool: True si suppression réussie
            
        Raises:
            StorageError: Si la suppression échoue
        """
        try:
            self.client.delete_object(
                Bucket=self.bucket_name,
                Key=file_key
            )
            
            logger.info("Fichier temporaire supprimé avec succès", file_key=file_key)
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            logger.error(
                "Erreur client lors de la suppression",
                error_code=error_code,
                file_key=file_key
            )
            raise StorageError(
                f"Erreur lors de la suppression: {error_code}",
                error_code=error_code
            )
        except Exception as e:
            logger.error(
                "Erreur inattendue lors de la suppression",
                error=str(e),
                file_key=file_key
            )
            raise StorageError(f"Erreur inattendue lors de la suppression: {e}")
    
    async def check_connection(self) -> bool:
        """
        Vérifie la connexion au bucket R2.
        
        Returns:
            bool: True si la connexion est OK
        """
        try:
            # D'abord tester la liste des buckets (plus rapide)
            buckets = self.client.list_buckets()
            bucket_names = [b['Name'] for b in buckets['Buckets']]
            
            if self.bucket_name not in bucket_names:
                logger.error(
                    "Bucket non trouvé dans la liste",
                    bucket_name=self.bucket_name,
                    available_buckets=bucket_names
                )
                return False
            
            # Ensuite tester l'accès au bucket spécifique
            self.client.list_objects_v2(
                Bucket=self.bucket_name,
                MaxKeys=1
            )
            
            logger.info(
                "Connexion R2 vérifiée avec succès",
                bucket_name=self.bucket_name
            )
            return True
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            logger.error(
                "Erreur client lors de la vérification R2",
                error_code=error_code,
                bucket_name=self.bucket_name,
                error_message=str(e)
            )
            return False
        except Exception as e:
            logger.error(
                "Erreur lors de la vérification de connexion R2",
                error=str(e),
                bucket_name=self.bucket_name
            )
            return False
    
    def _generate_temp_file_key(self, file_extension: str) -> str:
        """
        Génère une clé unique pour un fichier temporaire.
        
        Args:
            file_extension: Extension du fichier
            
        Returns:
            str: Clé unique du fichier
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        
        # Structure: temp/YYYYMMDD_HHMMSS_uniqueid.extension
        return f"temp/{timestamp}_{unique_id}{file_extension}"


# Instance globale du service
storage_service = StorageService()