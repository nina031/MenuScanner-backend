# run.py
"""
Script de démarrage pour le backend MenuScanner.
Place ce fichier à la racine du dossier backend/ (à côté de requirements.txt)
"""
import uvicorn
import sys
import os

# Ajouter le dossier app au path Python
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.main import app
from app.core.config import settings

if __name__ == "__main__":
    print("🍽️" + "="*50)
    print(f"🚀 Démarrage {settings.app_name} v{settings.app_version}")
    print("🍽️" + "="*50)
    print(f"📡 Serveur: http://{settings.host}:{settings.port}")
    print(f"📚 Documentation: http://{settings.host}:{settings.port}/docs")
    print(f"🔍 Health check: http://{settings.host}:{settings.port}/api/health")
    print(f"📤 Upload image: http://{settings.host}:{settings.port}/api/upload-image")
    print("🍽️" + "="*50)
    print("💡 Appuie sur Ctrl+C pour arrêter le serveur")
    print()
    
    try:
        uvicorn.run(
            "app.main:app",
            host=settings.host,
            port=settings.port,
            reload=settings.debug,
            log_level="info",
            access_log=True
        )
    except KeyboardInterrupt:
        print("\n🛑 Serveur arrêté par l'utilisateur")
    except Exception as e:
        print(f"\n❌ Erreur lors du démarrage: {e}")
        sys.exit(1)