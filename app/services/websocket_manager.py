import asyncio
import json
import uuid
from typing import Dict, Any, Optional
from fastapi import WebSocket, WebSocketDisconnect
import structlog

logger = structlog.get_logger()

class WebSocketManager:
    """Gestionnaire centralisé des connexions WebSocket."""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, connection_id: Optional[str] = None) -> str:
        """Connecte un WebSocket et retourne l'ID de connexion."""
        if not connection_id:
            connection_id = f"conn_{uuid.uuid4().hex[:12]}"
        
        await websocket.accept()
        self.active_connections[connection_id] = websocket
        
        logger.info("WebSocket connecté", connection_id=connection_id)
        
        # Envoyer le message de connexion immédiatement
        await self.send_to_connection(connection_id, {
            "type": "connected",
            "connection_id": connection_id,
            "message": "Connexion WebSocket établie"
        }, flush=True)
        
        return connection_id
    
    def disconnect(self, connection_id: str):
        """Déconnecte un WebSocket."""
        if connection_id in self.active_connections:
            del self.active_connections[connection_id]
            logger.info("WebSocket déconnecté", connection_id=connection_id)
    
    def is_connected(self, connection_id: str) -> bool:
        """Vérifie si une connexion est active."""
        return connection_id in self.active_connections
    
    async def send_to_connection(self, connection_id: str, message: Dict[str, Any], flush: bool = False):
        """Envoie un message à une connexion spécifique avec option de flush immédiat."""
        if connection_id not in self.active_connections:
            logger.warning("Connexion non trouvée", connection_id=connection_id)
            return False
        
        websocket = self.active_connections[connection_id]
        
        try:
            # Sérialiser le message
            message_json = json.dumps(message, ensure_ascii=False, default=str)
            
            # Envoi immédiat
            await websocket.send_text(message_json)
            
            # FLUSH IMMÉDIAT si demandé pour forcer l'envoi
            if flush:
                await asyncio.sleep(0.001)  # 1ms pour garantir l'envoi
                
            logger.info(
                f"Message envoyé{' (FLUSHED)' if flush else ''}",
                type=message.get('type'),
                connection_id=connection_id
            )
            
            return True
            
        except WebSocketDisconnect:
            logger.info("WebSocket déconnecté pendant l'envoi", connection_id=connection_id)
            self.disconnect(connection_id)
            return False
        except Exception as e:
            logger.error("Erreur envoi WebSocket", error=str(e), connection_id=connection_id)
            self.disconnect(connection_id)
            return False
    
    async def send_to_all(self, message: Dict[str, Any]):
        """Envoie un message à toutes les connexions actives."""
        if not self.active_connections:
            return
        
        disconnected = []
        
        for connection_id in self.active_connections:
            success = await self.send_to_connection(connection_id, message)
            if not success:
                disconnected.append(connection_id)
        
        # Nettoyer les connexions fermées
        for connection_id in disconnected:
            self.disconnect(connection_id)
    
    def get_connection_count(self) -> int:
        """Retourne le nombre de connexions actives."""
        return len(self.active_connections)
    
    def get_active_connections(self) -> list:
        """Retourne la liste des IDs de connexions actives."""
        return list(self.active_connections.keys())

# Instance globale du gestionnaire
websocket_manager = WebSocketManager()