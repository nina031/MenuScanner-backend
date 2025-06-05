# test_websocket.py
import asyncio
import websockets
import json
import requests
import time

async def test_websocket_flow():
    """Test complet du flux WebSocket."""
    
    print("🧪 Test du backend WebSocket MenuScanner")
    print("=" * 50)
    
    # 1. Se connecter au WebSocket
    print("1. Connexion au WebSocket...")
    uri = "ws://localhost:8000/api/ws"
    
    try:
        async with websockets.connect(uri) as websocket:
            print("✅ Connexion WebSocket établie")
            
            # Attendre le message de connexion
            connection_message = await websocket.recv()
            connection_data = json.loads(connection_message)
            print(f"📩 Message de connexion: {connection_data}")
            
            connection_id = connection_data.get("connection_id")
            if not connection_id:
                print("❌ Pas de connection_id reçu")
                return
            
            print(f"🔗 Connection ID: {connection_id}")
            
            # 2. Tester le ping
            print("\n2. Test ping...")
            ping_message = {
                "type": "ping",
                "timestamp": int(time.time())
            }
            await websocket.send(json.dumps(ping_message))
            
            pong_response = await websocket.recv()
            pong_data = json.loads(pong_response)
            print(f"📩 Pong reçu: {pong_data}")
            
            # 3. Simuler l'upload d'une image (sans vraie image pour ce test)
            print("\n3. Simulation upload...")
            print("⚠️  Pour un vrai test, utilisez l'endpoint /upload-and-process")
            print(f"   avec connection_id: {connection_id}")
            
            # 4. Écouter les messages pendant quelques secondes
            print("\n4. Écoute des messages WebSocket...")
            try:
                # Timeout après 5 secondes pour ce test
                message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                data = json.loads(message)
                print(f"📩 Message reçu: {data}")
            except asyncio.TimeoutError:
                print("⏰ Timeout - aucun message reçu (normal pour ce test)")
            
            print("\n✅ Test WebSocket terminé avec succès!")
            
    except Exception as e:
        print(f"❌ Erreur de connexion WebSocket: {e}")
        print("🔧 Vérifiez que le backend est démarré sur localhost:8000")


def test_health_check():
    """Test du health check via HTTP."""
    print("\n🏥 Test Health Check...")
    
    try:
        response = requests.get("http://localhost:8000/api/health")
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Health check OK: {data['status']}")
            print(f"📊 Services: {data['services']}")
        else:
            print(f"❌ Health check failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Erreur health check: {e}")


def test_ws_status():
    """Test du statut WebSocket via HTTP."""
    print("\n📊 Test WebSocket Status...")
    
    try:
        response = requests.get("http://localhost:8000/api/ws-status")
        if response.status_code == 200:
            data = response.json()
            print(f"✅ WebSocket status OK")
            print(f"🔗 Connexions actives: {data['data']['active_connections']}")
        else:
            print(f"❌ WebSocket status failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Erreur WebSocket status: {e}")


if __name__ == "__main__":
    print("🚀 Démarrage des tests...")
    
    # Tests HTTP d'abord
    test_health_check()
    test_ws_status()
    
    # Test WebSocket
    asyncio.run(test_websocket_flow())
    
    print("\n🎉 Tous les tests terminés!")
    print("\n📝 Pour tester avec une vraie image:")
    print("1. Connectez-vous au WebSocket ws://localhost:8000/api/ws")
    print("2. Récupérez votre connection_id")
    print("3. Faites un POST vers /api/upload-and-process avec votre image")
    print("4. Écoutez les messages sur le WebSocket")