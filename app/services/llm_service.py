# app/services/llm_service.py
import json
import re
import time
from typing import List, Tuple, Dict, Any, AsyncGenerator
from anthropic import Anthropic
import structlog

from app.core.config import settings
from app.core.exceptions import LLMError

logger = structlog.get_logger()


class LLMService:
    """Service de traitement LLM avec Claude pour l'analyse de menus."""
    
    def __init__(self):
        """Initialise le client Claude."""
        try:
            self.client = Anthropic(api_key=settings.claude_api_key)
            logger.info("Client Claude initialisé avec succès")
        except Exception as e:
            logger.error("Erreur lors de l'initialisation du client Claude", error=str(e))
            raise LLMError(f"Impossible d'initialiser le client Claude: {e}")
    
    def call_claude(self, text: str, prompt: str) -> str:
        """
        Appel générique à Claude - format liste définitif.
        """
        try:
            logger.info("Appel à Claude", text_length=len(text), prompt_length=len(prompt))
            
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=8192,
                temperature=0,
                system=prompt,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": str(text)  # Force en string
                            }
                        ]
                    }
                ]
            )
            
            logger.info("Réponse Claude reçue")
            return response.content[0].text
            
        except Exception as e:
            logger.error("Erreur lors de l'appel à Claude", error=str(e))
            raise LLMError(f"Erreur lors de l'appel à Claude: {e}")
    
    def detect_sections_and_title(self, ocr_text: str) -> Tuple[List[str], str]:
        """
        Détecte les sections et le titre du menu.
        
        Args:
            ocr_text: Texte OCR du menu
            
        Returns:
            Tuple[List[str], str]: (sections, menu_title)
        """
        DETECT_SECTIONS_PROMPT = """Analyse ce texte OCR de menu et retourne uniquement un JSON avec les noms des sections et le titre du restaurant/menu.

        Format EXACT:
        {
        "menu_title": "Nom du Restaurant/Menu",
        "sections": ["SECTION1", "SECTION2", "SECTION3"]
        }

        Instructions:
        1. Identifie le titre/nom du restaurant (généralement en haut du menu)
        2. Identifie automatiquement toutes les sections du menu (entrées, plats, desserts, pizzas, boissons, etc.)
        3. GARDE EXACTEMENT les noms de sections comme ils apparaissent dans le texte OCR - ne les traduis PAS, ne les modifie PAS
        4. Ne retourne QUE le JSON, rien d'autre"""

        response = self.call_claude(ocr_text, DETECT_SECTIONS_PROMPT)
        
        try:
            # Essayer de parser directement
            data = json.loads(response)
            return data["sections"], data["menu_title"]
        except json.JSONDecodeError:
            # Chercher le JSON dans la réponse
            json_match = re.search(r'\{[^}]*"menu_title"[^}]*"sections"[^}]*\}', response)
            if json_match:
                try:
                    json_str = json_match.group()
                    logger.debug("JSON extrait", json_str=json_str)
                    data = json.loads(json_str)
                    return data["sections"], data["menu_title"]
                except:
                    logger.warning("Erreur parsing JSON extrait")
            
            # Fallback
            sections = re.findall(r'"([A-Z][A-Z\sÀ-Ü]*)"', response)
            valid_sections = [s for s in sections if len(s.strip()) >= 3]
            return valid_sections, "Menu"
    
    def extract_section_content(self, ocr_text: str, section_name: str, all_sections: List[str]) -> str:
        """
        Extrait le contenu d'une section - utilisant l'algorithme original du notebook.
        """
        lines = ocr_text.split('\n')
        content = []
        capturing = False
        
        for line in lines:
            # Vérifier si c'est le début de notre section (mot entier avec frontières)
            if re.search(r'\b' + re.escape(section_name.upper()) + r'\b', line.upper()):
                capturing = True
                # Ne pas ajouter la ligne avec le nom de section
                continue
            elif capturing:
                # Arrêter si on trouve une autre section de la liste détectée (mot entier)
                if any(re.search(r'\b' + re.escape(s.upper()) + r'\b', line.upper()) for s in all_sections if s != section_name):
                    break
                content.append(line)
        
        result = '\n'.join(content)
        
        logger.info("Extraction avec algorithme original", 
                section=section_name, 
                content_length=len(result),
                content_preview=result[:100] if result else "VIDE")
        
        return result
    
    def analyze_section(self, section_content: str, section_name: str) -> Dict[str, Any]:
        """
        Analyse une section de menu.
        
        Args:
            section_content: Contenu de la section
            section_name: Nom de la section
            
        Returns:
            Dict: Section analysée avec items
        """
        ANALYZE_SECTION_PROMPT = f"""Analyse cette section de menu nommée "{section_name}" et retourne uniquement un JSON valide suivant cette structure:

        {{
        "name": "nom_section_corrigé",
        "items": [
            {{
            "name": "nom_plat",
            "price": {{"value": 12.50, "currency": "€"}},
            "description": "description_complète",
            "ingredients": ["ingrédient1", "ingrédient2"],
            "dietary": ["végétarien"]
            }}
        ]
        }}

        Instructions:
        1. CORRIGE les erreurs OCR évidentes dans le nom de section "{section_name}":
        - "PRZE" → "PIZZE"
        - "DOLC" → "DOLCI"
        - "ANTPASTI" → "ANTIPASTI"
        - "NSALATE" → "INSALATE"
        - "CARNE" → garde "CARNE" (correct)
        - "PASTA" → garde "PASTA" (correct)
        - etc.
        Utilise le nom corrigé dans le champ "name" du JSON
        2. Pour chaque item: nom, prix, description, ingrédients (déduis-les de la description si nécessaire)
        3. Prix: utilise uniquement €, $, £, CHF pour currency. Si autre chose ou illisible, mets null
        4. DÉTECTION ET TRADUCTION DE LANGUE:
        - Détecte la langue majoritaire du menu
        - Si langue du menu = français → PAS de traduction
        - Si langue du menu = langue avec même alphabet que l'utilisateur → traduis les descriptions MAIS garde les spécialités/ingrédients authentiques en langue originale
        - Si langue du menu = langue avec alphabet différent de l'utilisateur → TRADUIS TOUT car l'utilisateur ne peut pas lire ces caractères

        IMPORTANT - Régimes alimentaires (sois très prudent):
        - Si tu as un grand doute, laisse dietary vide []
        - Règles strictes:
        * "végétarien": AUCUNE viande, poisson, fruits de mer (mais œufs/lait OK)
        * "végétalien": AUCUN produit animal (pas de viande, poisson, œufs, lait, miel, beurre)
        * "sans_gluten": AUCUN blé, orge, seigle, avoine (attention aux sauces, panure)
        * "sans_lactose": AUCUN lait, crème, fromage, beurre, yaourt

        ATTENTION - VIANDES (jamais végétarien):
        - Jambon, jambon blanc, jambon cru, prosciutto = VIANDE
        - Bacon, lardons, pancetta = VIANDE  
        - Saucisse, chorizo, pepperoni = VIANDE
        - Salami, coppa, bresaola = VIANDE
        - Bœuf, porc, agneau, veau = VIANDE
        - Poulet, canard, dinde = VIANDE

        IMPORTANT: Inclus TOUS les éléments présents dans cette section.
        Retourne UNIQUEMENT le JSON, sans texte additionnel."""

        response = self.call_claude(section_content, ANALYZE_SECTION_PROMPT)
        
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # Fallback avec le bon nom de section
            return {"name": section_name, "items": []}
    
    async def stream_menu_processing(self, ocr_text: str) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Traite un menu en streaming, section par section.
        
        Args:
            ocr_text: Texte OCR complet du menu
            
        Yields:
            Dict: Messages de streaming avec les sections traitées
        """
        start_time = time.time()
        
        logger.info("Début du traitement LLM en streaming")

        # 🔍 DEBUG: Afficher le texte OCR complet
        logger.info("=== DEBUT TEXTE OCR COMPLET ===")
        logger.info("Texte OCR brut", full_text=ocr_text)
        logger.info("=== FIN TEXTE OCR COMPLET ===")
        
        # Étape 1: Détecter les sections et le titre
        yield {
            "type": "status",
            "message": "Détection des sections du menu...",
            "step": "detection"
        }
        
        sections, menu_title = self.detect_sections_and_title(ocr_text)
        
        logger.info(
            "Sections détectées",
            menu_title=menu_title,
            sections_count=len(sections),
            sections=sections
        )
        
        # Envoyer les métadonnées du menu
        yield {
            "type": "menu_metadata",
            "menu_name": menu_title,
            "sections_count": len(sections),
            "sections": sections
        }
        
        # Étape 2: Extraire le contenu de chaque section
        yield {
            "type": "status",
            "message": "Extraction du contenu des sections...",
            "step": "extraction"
        }
        
        sections_with_content = []
        for section in sections:
            content = self.extract_section_content(ocr_text, section, sections)
            sections_with_content.append({
                "name": section,
                "content": content
            })
        
        # Étape 3: Analyser chaque section et streamer les résultats
        yield {
            "type": "status",
            "message": "Analyse des sections en cours...",
            "step": "analysis"
        }
        
        for i, section_data in enumerate(sections_with_content, 1):
            section_name = section_data["name"]
            section_content = section_data["content"]
            
            # Indiquer le début du traitement de cette section
            yield {
                "type": "section_start",
                "section_name": section_name,
                "section_index": i,
                "total_sections": len(sections_with_content)
            }
            
            logger.info(
                "Traitement section",
                section_index=f"{i}/{len(sections_with_content)}",
                section_name=section_name
            )
            
            section_start_time = time.time()
            
            # Analyser la section
            analyzed = self.analyze_section(section_content, section_name)
            
            section_duration = time.time() - section_start_time
            
            logger.info(
                "Section traitée",
                section_name=section_name,
                items_count=len(analyzed.get("items", [])),
                duration_seconds=round(section_duration, 2)
            )
            
            # Envoyer la section analysée
            yield {
                "type": "section_complete",
                "section": analyzed,
                "section_index": i,
                "total_sections": len(sections_with_content),
                "processing_time_seconds": round(section_duration, 2)
            }
        
        # Traitement terminé
        total_duration = time.time() - start_time
        
        logger.info(
            "Traitement LLM streaming terminé",
            total_duration_seconds=round(total_duration, 2),
            average_per_section=round(total_duration/len(sections), 2),
            total_sections=len(sections)
        )
        
        yield {
            "type": "complete",
            "message": "Traitement terminé",
            "total_duration_seconds": round(total_duration, 2),
            "total_sections": len(sections)
        }


# Instance globale du service
llm_service = LLMService()