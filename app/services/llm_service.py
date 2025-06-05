import json
import time
from typing import Dict, Any, List
from anthropic import Anthropic
from anthropic.types import MessageParam
import structlog

from app.core.config import settings
from app.core.exceptions import LLMError
from app.models.response import MenuData, MenuSection, MenuItem, Price

logger = structlog.get_logger()


class LLMService:
    """Service de traitement LLM avec Claude API."""
    
    def __init__(self):
        """Initialise le client Claude."""
        try:
            self.client = Anthropic(api_key=settings.claude_api_key)
            logger.info("Client Claude initialisé avec succès")
        except Exception as e:
            logger.error("Erreur lors de l'initialisation du client Claude", error=str(e))
            raise LLMError(f"Impossible d'initialiser le client Claude: {e}")
    
    async def structure_menu_text(self, ocr_text: str, language_hint: str = "fr") -> MenuData:
        """
        Structure le texte OCR en menu JSON avec Claude (méthode originale).
        
        Args:
            ocr_text: Texte brut extrait par OCR
            language_hint: Langue principale du menu
            
        Returns:
            MenuData: Menu structuré
            
        Raises:
            LLMError: Si la structuration échoue
        """
        start_time = time.time()
        
        try:
            logger.info(
                "Début structuration LLM",
                text_length=len(ocr_text),
                language=language_hint
            )
            
            # Construire le prompt système
            system_prompt = self._build_system_prompt(language_hint)
            
            # Préparer les messages
            messages: list[MessageParam] = [
                {
                    "role": "user",
                    "content": f"Texte OCR à analyser:\n\n{ocr_text}"
                }
            ]
            
            # Appel à Claude
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=8192,
                temperature=0,
                system=system_prompt,
                messages=messages
            )
            
            # Extraire le contenu de la réponse
            response_text = response.content[0].text if response.content else ""
            
            # Parser le JSON retourné par Claude
            menu_data = self._parse_claude_response(response_text)
            
            processing_time = time.time() - start_time
            
            logger.info(
                "Structuration LLM terminée avec succès",
                sections_count=len(menu_data.menu.sections),
                total_items=sum(len(section.items) for section in menu_data.menu.sections),
                processing_time=processing_time,
                tokens_used=getattr(response.usage, 'input_tokens', 0) + getattr(response.usage, 'output_tokens', 0)
            )
            
            return menu_data
            
        except json.JSONDecodeError as e:
            logger.error("Erreur de parsing JSON de la réponse Claude", error=str(e))
            raise LLMError(
                f"Réponse Claude invalide (JSON malformé): {e}",
                error_code="INVALID_JSON_RESPONSE"
            )
            
        except Exception as e:
            logger.error("Erreur inattendue lors de la structuration LLM", error=str(e))
            
            # Gestion spécifique des erreurs Claude
            if "rate_limit" in str(e).lower():
                raise LLMError(
                    "Limite de taux Claude atteinte",
                    error_code="CLAUDE_RATE_LIMIT"
                )
            elif "invalid_api_key" in str(e).lower():
                raise LLMError(
                    "Clé API Claude invalide",
                    error_code="CLAUDE_AUTH_ERROR"
                )
            else:
                raise LLMError(f"Erreur Claude: {e}")

    async def detect_sections_and_title(self, ocr_text: str) -> Dict[str, Any]:
        """
        Détecte uniquement les sections et le titre du menu.
        
        Args:
            ocr_text: Texte OCR complet
            
        Returns:
            Dict contenant menu_title et sections
        """
        start_time = time.time()
        
        try:
            logger.info("Début détection sections", text_length=len(ocr_text))
            
            prompt = """Analyse ce texte OCR de menu et retourne UNIQUEMENT un JSON avec les sections et le titre:

{
  "menu_title": "Nom du restaurant/menu ou null",
  "sections": ["SECTION1", "SECTION2", "SECTION3"]
}

Instructions:
1. Identifie le titre/nom du restaurant (généralement en haut du menu)
2. Liste toutes les sections du menu (ENTRÉES, PLATS, DESSERTS, PIZZAS, etc.)
3. Garde les noms EXACTS des sections comme ils apparaissent dans le texte
4. Retourne UNIQUEMENT le JSON, sans texte additionnel"""
            
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1000,
                temperature=0,
                system=prompt,
                messages=[{"role": "user", "content": ocr_text}]
            )
            
            response_text = response.content[0].text if response.content else ""
            cleaned_response = self._clean_json_response(response_text)
            result = json.loads(cleaned_response)
            
            processing_time = time.time() - start_time
            
            logger.info(
                "Détection sections terminée",
                menu_title=result.get("menu_title"),
                sections_count=len(result.get("sections", [])),
                processing_time=processing_time
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Erreur détection sections: {e}")
            return {"menu_title": "Menu", "sections": []}

    def extract_sections_content(self, ocr_text: str, section_names: List[str]) -> Dict[str, str]:
        """
        Extrait le contenu de chaque section du texte OCR.
        
        Args:
            ocr_text: Texte OCR complet
            section_names: Liste des noms de sections détectées
            
        Returns:
            Dict mapping nom_section -> contenu_section
        """
        sections_content = {}
        lines = ocr_text.split('\n')
        
        for section_name in section_names:
            content = []
            capturing = False
            
            for line in lines:
                # Début de notre section (recherche flexible)
                if section_name.upper() in line.upper().replace(" ", ""):
                    capturing = True
                    continue
                elif capturing:
                    # Arrêter si on trouve une autre section
                    if any(other_section.upper() in line.upper().replace(" ", "")
                          for other_section in section_names 
                          if other_section != section_name):
                        break
                    content.append(line)
            
            sections_content[section_name] = '\n'.join(content).strip()
        
        logger.info(
            "Extraction contenu sections terminée",
            sections_extracted=len(sections_content)
        )
        
        return sections_content

    async def analyze_single_section(self, section_content: str, section_name: str, language_hint: str) -> MenuSection:
        """
        Analyse une seule section et retourne les items structurés.
        
        Args:
            section_content: Contenu brut de la section
            section_name: Nom de la section
            language_hint: Langue du menu
            
        Returns:
            MenuSection: Section structurée avec ses items
        """
        start_time = time.time()
        
        try:
            logger.info("Début analyse section", section_name=section_name)
            
            prompt = f"""Analyse cette section "{section_name}" et retourne UNIQUEMENT un JSON valide:

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
1. CORRIGE les erreurs OCR évidentes dans le nom de section "{section_name}"
2. Extrais TOUS les plats de cette section
3. Prix: utilise €, $, £, CHF pour currency. Si illisible, mets null
4. Langue: {language_hint}
5. Régimes alimentaires (prudent): végétarien, végétalien, sans_gluten, sans_lactose
6. Si grand doute sur régime, laisse dietary vide []

RÈGLES RÉGIMES:
- végétarien: AUCUNE viande/poisson (œufs/lait OK)
- végétalien: AUCUN produit animal
- sans_gluten: AUCUN blé/orge/seigle/avoine
- sans_lactose: AUCUN lait/crème/fromage/beurre

VIANDES (jamais végétarien): jambon, bacon, pancetta, saucisse, chorizo, salami, coppa, bresaola, bœuf, porc, agneau, veau, poulet, canard, dinde

Retourne UNIQUEMENT le JSON."""
            
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4000,
                temperature=0,
                system=prompt,
                messages=[{"role": "user", "content": section_content}]
            )
            
            response_text = response.content[0].text if response.content else ""
            cleaned_response = self._clean_json_response(response_text)
            parsed_data = json.loads(cleaned_response)
            
            # Convertir en MenuSection avec validation
            items = []
            for item_data in parsed_data.get("items", []):
                try:
                    # Créer Price avec validation
                    price_data = item_data.get("price", {"value": 0, "currency": "€"})
                    price = Price(
                        value=float(price_data.get("value", 0)),
                        currency=price_data.get("currency", "€")
                    )
                    
                    # Créer MenuItem
                    menu_item = MenuItem(
                        name=item_data.get("name", ""),
                        price=price,
                        description=item_data.get("description", ""),
                        ingredients=item_data.get("ingredients", []),
                        dietary=item_data.get("dietary", [])
                    )
                    
                    items.append(menu_item)
                    
                except Exception as item_error:
                    logger.warning(f"Erreur item {item_data.get('name', 'unknown')}: {item_error}")
                    continue
            
            menu_section = MenuSection(
                name=parsed_data.get("name", section_name),
                items=items
            )
            
            processing_time = time.time() - start_time
            
            logger.info(
                "Analyse section terminée",
                section_name=section_name,
                corrected_name=menu_section.name,
                items_count=len(menu_section.items),
                processing_time=processing_time
            )
            
            return menu_section
            
        except Exception as e:
            logger.error(f"Erreur analyse section {section_name}: {e}")
            return MenuSection(name=section_name, items=[])
    
    def _build_system_prompt(self, language_hint: str) -> str:
        """
        Construit le prompt système pour Claude (méthode originale).
        
        Args:
            language_hint: Langue du menu
            
        Returns:
            str: Prompt système optimisé
        """
        return f"""Tu es un expert en analyse de menus de restaurant. Analyse le texte OCR fourni et retourne UNIQUEMENT un JSON valide suivant cette structure exacte:

{{
  "menu": {{
    "name": "nom_restaurant_si_detecte_ou_null",
    "sections": [
      {{
        "name": "nom_section",
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
    ]
  }}
}}

INSTRUCTIONS CRITIQUES:
1. Retourne UNIQUEMENT le JSON, sans texte additionnel avant ou après
2. Identifie automatiquement les sections (entrées, plats, desserts, pizzas, boissons, etc.)
3. Pour chaque item: nom, prix, description, ingrédients (déduis-les de la description)
4. Prix: utilise uniquement €, $, £, CHF pour currency. Si illisible/autre, mets null
5. Langue principale: {language_hint}

RÉGIMES ALIMENTAIRES (sois très prudent):
- Si grand doute, laisse dietary vide []
- Règles strictes:
  * "végétarien": AUCUNE viande, poisson, fruits de mer (œufs/lait OK)
  * "végétalien": AUCUN produit animal (pas viande, poisson, œufs, lait, miel, beurre)
  * "sans_gluten": AUCUN blé, orge, seigle, avoine (attention sauces, panure)
  * "sans_lactose": AUCUN lait, crème, fromage, beurre, yaourt

VIANDES (jamais végétarien):
Jambon, bacon, pancetta, saucisse, chorizo, salami, coppa, bresaola, bœuf, porc, agneau, veau, poulet, canard, dinde

EXEMPLES:
- Salade verte simple = ["végétarien", "végétalien"]
- Pizza margherita = ["végétarien"] (fromage = lait)
- Steak frites = ["sans_gluten", "sans_lactose"] (si frites maison)
- Pâtes carbonara = [] (œufs + lardons = ni végétarien ni végétalien)

IMPORTANT: Inclus TOUS les éléments du texte OCR. Ne laisse rien de côté."""

    def _parse_claude_response(self, response_text: str) -> MenuData:
        """
        Parse la réponse JSON de Claude en MenuData.
        
        Args:
            response_text: Réponse brute de Claude
            
        Returns:
            MenuData: Données structurées validées
            
        Raises:
            LLMError: Si le parsing échoue
        """
        try:
            # Nettoyer la réponse (enlever éventuels caractères avant/après JSON)
            cleaned_response = self._clean_json_response(response_text)
            
            # Parser le JSON
            parsed_data = json.loads(cleaned_response)
            
            # Valider et créer MenuData avec Pydantic
            menu_data = MenuData(**parsed_data)
            
            # Validation additionnelle
            self._validate_menu_data(menu_data)
            
            return menu_data
            
        except json.JSONDecodeError as e:
            logger.error(
                "Erreur parsing JSON Claude",
                error=str(e),
                response_preview=response_text[:200]
            )
            raise LLMError(f"JSON invalide de Claude: {e}")
            
        except Exception as e:
            logger.error(
                "Erreur validation MenuData",
                error=str(e),
                response_preview=response_text[:200]
            )
            raise LLMError(f"Données menu invalides: {e}")
    
    def _clean_json_response(self, response_text: str) -> str:
        """
        Nettoie la réponse de Claude pour extraire le JSON.
        
        Args:
            response_text: Réponse brute
            
        Returns:
            str: JSON nettoyé
        """
        # Chercher le début et la fin du JSON
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}') + 1
        
        if start_idx == -1 or end_idx == 0:
            raise LLMError("Aucun JSON trouvé dans la réponse Claude")
        
        return response_text[start_idx:end_idx]
    
    def _validate_menu_data(self, menu_data: MenuData) -> None:
        """
        Validation additionnelle des données menu.
        
        Args:
            menu_data: Données à valider
            
        Raises:
            LLMError: Si validation échoue
        """
        if not menu_data.menu.sections:
            raise LLMError("Aucune section trouvée dans le menu")
        
        total_items = sum(len(section.items) for section in menu_data.menu.sections)
        if total_items == 0:
            raise LLMError("Aucun item trouvé dans le menu")
        
        # Vérifier que les prix sont cohérents
        for section in menu_data.menu.sections:
            for item in section.items:
                if item.price.value < 0:
                    logger.warning(f"Prix négatif détecté: {item.name} = {item.price.value}")
                if item.price.value > 1000:
                    logger.warning(f"Prix très élevé détecté: {item.name} = {item.price.value}")
        
        logger.info(
            "Validation menu réussie",
            sections=len(menu_data.menu.sections),
            total_items=total_items,
            restaurant_name=menu_data.menu.name
        )
    
    async def check_connection(self) -> bool:
        """
        Vérifie la connexion à Claude API.
        
        Returns:
            bool: True si la connexion est OK
        """
        try:
            # Test simple avec une requête minimale
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=50,
                temperature=0,
                messages=[
                    {
                        "role": "user",
                        "content": "Dis juste 'OK' si tu fonctionnes."
                    }
                ]
            )
            
            response_text = response.content[0].text if response.content else ""
            
            logger.info("Connexion Claude vérifiée avec succès", response=response_text)
            return True
            
        except Exception as e:
            logger.error("Erreur lors du test de connexion Claude", error=str(e))
            return False


# Instance globale du service
llm_service = LLMService()