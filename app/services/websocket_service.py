
# app/services/websocket_service.py
import json
import uuid
from typing import Dict, Set, Optional
from fastapi import WebSocket, WebSocketDisconnect
import structlog

logger = structlog.get_logger()


class ConnectionManager:
    """Gestionnaire des connexions WebSocket."""
    
    def __init__(self):
        # Dictionnaire des connexions actives : {connection_id: websocket}
        self.active_connections: Dict[str, WebSocket] = {}
        # Dictionnaire des scan_id associés aux connexions : {scan_id: connection_id}
        self.scan_connections: Dict[str, str] = {}
    
    async def connect(self, websocket: WebSocket) -> str:
        """
        Accepte une nouvelle connexion WebSocket.
        
        Returns:
            str: ID unique de la connexion
        """
        await websocket.accept()
        connection_id = f"conn_{uuid.uuid4().hex[:12]}"
        self.active_connections[connection_id] = websocket
        
        logger.info("Nouvelle connexion WebSocket", connection_id=connection_id)
        
        # Envoyer message de confirmation de connexion
        await self.send_message(connection_id, {
            "type": "connected",
            "connection_id": connection_id,
            "message": "Connexion WebSocket établie"
        })
        
        return connection_id
    
    def disconnect(self, connection_id: str, scan_id: Optional[str] = None):
        """Déconnecte une connexion WebSocket."""
        if connection_id in self.active_connections:
            del self.active_connections[connection_id]
            logger.info("Connexion WebSocket fermée", connection_id=connection_id)
        
        # Nettoyer l'association scan_id si elle existe
        if scan_id and scan_id in self.scan_connections:
            del self.scan_connections[scan_id]
    
    def associate_scan(self, connection_id: str, scan_id: str):
        """Associe un scan_id à une connexion."""
        self.scan_connections[scan_id] = connection_id
        logger.info("Scan associé à la connexion", connection_id=connection_id, scan_id=scan_id)
    
    async def send_message(self, connection_id: str, message: Dict) -> bool:
        """
        Envoie un message à une connexion spécifique.
        
        Args:
            connection_id: ID de la connexion
            message: Message à envoyer
            
        Returns:
            bool: True si envoyé avec succès
        """
        if connection_id not in self.active_connections:
            logger.warning("Tentative d'envoi vers connexion inexistante", connection_id=connection_id)
            return False
        
        try:
            websocket = self.active_connections[connection_id]
            await websocket.send_text(json.dumps(message, ensure_ascii=False))
            return True
        except Exception as e:
            logger.error(
                "Erreur envoi message WebSocket", 
                connection_id=connection_id, 
                error=str(e)
            )
            # Nettoyer la connexion fermée
            self.disconnect(connection_id)
            return False
    
    async def send_to_scan(self, scan_id: str, message: Dict) -> bool:
        """
        Envoie un message à la connexion associée à un scan_id.
        
        Args:
            scan_id: ID du scan
            message: Message à envoyer
            
        Returns:
            bool: True si envoyé avec succès
        """
        if scan_id not in self.scan_connections:
            logger.warning("Aucune connexion associée au scan", scan_id=scan_id)
            return False
        
        connection_id = self.scan_connections[scan_id]
        return await self.send_message(connection_id, message)
    
    async def broadcast(self, message: Dict):
        """Diffuse un message à toutes les connexions actives."""
        disconnected = []
        
        for connection_id, websocket in self.active_connections.items():
            try:
                await websocket.send_text(json.dumps(message, ensure_ascii=False))
            except Exception as e:
                logger.error("Erreur broadcast", connection_id=connection_id, error=str(e))
                disconnected.append(connection_id)
        
        # Nettoyer les connexions fermées
        for connection_id in disconnected:
            self.disconnect(connection_id)
    
    def get_connection_count(self) -> int:
        """Retourne le nombre de connexions actives."""
        return len(self.active_connections)
    
    def get_scan_connection(self, scan_id: str) -> Optional[str]:
        """Retourne l'ID de connexion associé à un scan."""
        return self.scan_connections.get(scan_id)


# Instance globale du gestionnaire de connexions
connection_manager = ConnectionManager()