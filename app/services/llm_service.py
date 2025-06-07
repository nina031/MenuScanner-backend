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
                model="claude-3-5-haiku-20241022",
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
1. OBLIGATOIRE: Génère TOUJOURS un titre. Identifie d'abord le nom du restaurant s'il est présent dans le texte. Sinon, crée un titre descriptif représentatif du type de cuisine (exemple: "Restaurant Italien", "Brasserie Française", "Pizzeria"). Ne jamais retourner null pour le titre
2. Liste toutes les sections du menu (ENTRÉES, PLATS, DESSERTS, PIZZAS, etc.)
3. CRUCIAL: Copie EXACTEMENT les noms des sections tels qu'ils apparaissent dans le texte OCR - ne change AUCUN caractère, même les erreurs d'OCR, accents manqués, espaces bizarres, ou fautes de frappe
4. Exemple: si le texte contient "ENTREES" avec accent manqué, garde "ENTREES", pas "ENTRÉES"
5. Exemple: si le texte contient "P1ZZAS" avec OCR défaillant, garde "P1ZZAS", pas "PIZZAS"
6. Retourne UNIQUEMENT le JSON, sans texte additionnel"""
            
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
            
            # Log détaillé des sections détectées
            sections_list = result.get("sections", [])
            menu_title = result.get("menu_title")
            
            logger.info(
                "📋 SECTIONS DÉTECTÉES",
                menu_title=menu_title,
                sections_count=len(sections_list),
                sections_list=sections_list,
                processing_time=processing_time
            )
            
            # Log spécifique pour le titre
            if menu_title:
                logger.info(f"🏪 TITRE DU MENU: {menu_title}")
            else:
                logger.info("⚠️ Aucun titre de menu détecté")
            
            # Log spécifique pour chaque section
            for i, section in enumerate(sections_list, 1):
                logger.info(f"📂 Section {i}/{len(sections_list)}: {section}")
            
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
                    # Arrêter si on trouve une autre section (correspondance exacte uniquement)
                    line_clean = line.upper().replace(" ", "").strip()
                    found_other_section = False
                    
                    for other_section in section_names:
                        if other_section != section_name:
                            other_clean = other_section.upper().replace(" ", "")
                            # Correspondance exacte seulement - pas de sous-chaîne
                            if line_clean == other_clean:
                                found_other_section = True
                                break
                    
                    if found_other_section:
                        break
                    content.append(line)
            
            sections_content[section_name] = '\n'.join(content).strip()
        
        # Log détaillé du contenu extrait pour chaque section
        logger.info(
            "📝 EXTRACTION CONTENU SECTIONS TERMINÉE",
            sections_extracted=len(sections_content)
        )
        
        # Log du contenu de chaque section avec aperçu
        for section_name, content in sections_content.items():
            content_preview = content[:100].replace('\n', ' ') if content else "[VIDE]"
            logger.info(
                f"📄 CONTENU SECTION '{section_name}'",
                section_name=section_name,
                content_length=len(content),
                content_preview=content_preview + ("..." if len(content) > 100 else "")
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
      "dietary": ["végétarien"],
      "allergens": ["Gluten", "Produits laitiers"]
    }}
  ]
}}

Instructions:
1. CORRIGE les erreurs OCR évidentes dans le nom de section "{section_name}"
2. Extrais TOUS les plats de cette section
3. Prix: utilise €, $, £, CHF pour currency. Si illisible, mets null
4. Langue: {language_hint}
5. Régimes alimentaires (prudent): végétarien, vegan, pescetarien
6. Si grand doute sur régime, laisse dietary vide []
7. ALLERGÈNES: OBLIGATOIRE - Liste des allergènes présents (liste vide [] si aucun) parmi cette liste officielle UE:
   ["Gluten", "Crustacés", "Œufs", "Poissons", "Arachides", "Soja", "Produits laitiers", "Fruits à coque", "Céleri", "Moutarde", "Sésame", "Sulfites", "Lupin", "Mollusques"]

RÈGLES RÉGIMES:
- végétarien: AUCUNE viande/poisson (œufs/lait OK)
- vegan: AUCUN produit animal (pas viande, poisson, œufs, lait, miel, beurre)
- pescetarien: AUCUNE viande (poisson/fruits de mer OK, œufs/lait OK)

RÈGLES ALLERGÈNES (ANALYSE OBLIGATOIRE):
- Gluten: blé, pâtes, pain, pizza, panure, farine, biscuits, semoule
- Produits laitiers: fromage, crème, beurre, lait, mascarpone, parmesan, mozzarella, burrata, gorgonzola, ricotta, yaourt
- Œufs: œufs entiers, mayo, carbonara, certaines pâtes fraîches
- Fruits à coque: noisettes, amandes, noix, pistaches, pignons de pin, noix de cajou
- Poissons: thon, anchois, saumon, morue, etc.
- Crustacés: crevettes, langoustines, crabes, homard
- Mollusques: moules, huîtres, escargots, poulpes

EXEMPLES CONCRETS:
- Pizza margherita → ["Gluten", "Produits laitiers"] (pâte + mozzarella)
- Salade César → ["Œufs", "Produits laitiers"] (mayo + parmesan)
- Pâtes carbonara → ["Gluten", "Œufs", "Produits laitiers"] (pâtes + œufs + fromage)
- Risotto aux champignons → ["Produits laitiers"] (parmesan)
- Saumon grillé → ["Poissons"]
- Salade verte simple → [] (aucun allergène)

IMPORTANT: Le champ "allergens" doit TOUJOURS être présent dans le JSON, même si c'est une liste vide [].

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
            
            # DEBUG: Log de la réponse LLM pour diagnostiquer les allergènes
            logger.info(
                f"🧪 DEBUG LLM RESPONSE pour section {section_name}",
                section_name=section_name,
                response_preview=cleaned_response[:500] + "..." if len(cleaned_response) > 500 else cleaned_response
            )
            
            # Convertir en MenuSection avec validation
            items = []
            total_items_in_response = len(parsed_data.get("items", []))
            logger.info(f"🧪 PARSING {total_items_in_response} items pour section {section_name}")
            
            for index, item_data in enumerate(parsed_data.get("items", [])):
                item_name = item_data.get("name", f"Item_{index}")
                logger.info(f"🧪 PARSING item {index+1}/{total_items_in_response}: '{item_name}'")
                try:
                    # Créer Price avec validation robuste
                    price_data = item_data.get("price", {"value": 0, "currency": "€"})
                    
                    # Gérer les cas où price est null ou invalide
                    if price_data is None or not isinstance(price_data, dict):
                        logger.warning(f"Prix invalide pour '{item_name}': {price_data}, utilisation prix par défaut")
                        price_data = {"value": 0, "currency": "€"}
                    
                    # Gérer les cas où value est null, string, ou invalide
                    price_value = price_data.get("value", 0)
                    if price_value is None:
                        price_value = 0
                    elif isinstance(price_value, str):
                        try:
                            price_value = float(price_value.replace(",", "."))
                        except ValueError:
                            logger.warning(f"Prix string invalide pour '{item_name}': '{price_value}', utilisation 0")
                            price_value = 0
                    
                    price = Price(
                        value=float(price_value),
                        currency=price_data.get("currency", "€") or "€"
                    )
                    
                    # Créer MenuItem avec gestion gracieuse des allergènes
                    allergens_detected = item_data.get("allergens", [])
                    
                    # S'assurer que allergens est une liste valide
                    if not isinstance(allergens_detected, list):
                        logger.warning(f"Allergènes invalides pour '{item_name}': {allergens_detected}, utilisation liste vide")
                        allergens_detected = []
                    
                    menu_item = MenuItem(
                        name=item_data.get("name", "Plat sans nom"),
                        price=price,
                        description=item_data.get("description", ""),
                        ingredients=item_data.get("ingredients", []) if isinstance(item_data.get("ingredients"), list) else [],
                        dietary=item_data.get("dietary", []) if isinstance(item_data.get("dietary"), list) else [],
                        allergens=allergens_detected
                    )
                    
                    # DEBUG: Log des allergènes par item
                    if allergens_detected:
                        logger.info(
                            f"🧪 ALLERGÈNES DÉTECTÉS pour '{menu_item.name}': {allergens_detected}"
                        )
                    else:
                        logger.info(
                            f"🧪 AUCUN ALLERGÈNE pour '{menu_item.name}'"
                        )
                    
                    items.append(menu_item)
                    logger.info(f"✅ ITEM AJOUTÉ: '{item_name}'")
                    
                except Exception as item_error:
                    logger.error(f"❌ ERREUR PARSING ITEM '{item_name}': {item_error}")
                    logger.error(f"❌ DONNÉES ITEM: {item_data}")
                    continue
            
            menu_section = MenuSection(
                name=parsed_data.get("name", section_name),
                items=items
            )
            
            logger.info(
                f"🧪 SECTION FINALE '{section_name}': {len(items)}/{total_items_in_response} items conservés"
            )
            
            processing_time = time.time() - start_time
            
            # Log détaillé de l'analyse de section
            logger.info(
                f"✅ ANALYSE SECTION '{section_name}' TERMINÉE",
                section_name=section_name,
                corrected_name=menu_section.name,
                items_count=len(menu_section.items),
                processing_time=processing_time
            )
            
            # Log des items détectés dans cette section
            if menu_section.items:
                logger.info(f"🍽️ Items détectés dans '{menu_section.name}':")
                for i, item in enumerate(menu_section.items, 1):
                    price_str = f"{item.price.value}{item.price.currency}" if item.price.value > 0 else "Prix non détecté"
                    dietary_str = ", ".join(item.dietary) if item.dietary else "Aucun régime spécial"
                    
                    logger.info(
                        f"  {i}. {item.name}",
                        item_name=item.name,
                        price=price_str,
                        description_length=len(item.description) if item.description else 0,
                        ingredients_count=len(item.ingredients),
                        dietary=dietary_str
                    )
            else:
                logger.warning(f"⚠️ Aucun item détecté dans la section '{menu_section.name}'")
            
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
- Salade verte simple = ["végétarien", "vegan", "pescetarien"]
- Pizza margherita = ["végétarien", "pescetarien"] (fromage = lait, donc pas vegan)
- Saumon grillé = ["pescetarien"] (poisson OK pour pescetarien seulement)
- Pâtes carbonara = [] (œufs + lardons = ni végétarien ni vegan ni pescetarien)

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