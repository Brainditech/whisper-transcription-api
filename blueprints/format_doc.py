from flask import Blueprint, request, jsonify
import mistune  # Pour parser le Markdown (version v2)
from google.oauth2 import service_account
from googleapiclient.discovery import build
import re
import logging
import json
import unicodedata
import regex  # module 'regex' supportant la notion de grapheme clusters, installer via "pip install regex"

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

format_doc_bp = Blueprint('format_doc', __name__)

# --- Configuration de l'API Google Docs ---
SCOPES = ["https://www.googleapis.com/auth/documents"]
SERVICE_ACCOUNT_FILE = "service_account.json"  # Ajustez le chemin si nécessaire

def get_google_docs_service():
    """Crée et retourne un service Google Docs authentifié."""
    try:
        credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        logger.info("Service Google Docs authentifié avec succès.")
        return build('docs', 'v1', credentials=credentials)
    except FileNotFoundError:
        logger.error(f"CRITICAL: Fichier de compte de service '{SERVICE_ACCOUNT_FILE}' non trouvé.")
        raise
    except Exception as e:
        logger.error(f"CRITICAL: Erreur lors de la création du service Google Docs: {e}", exc_info=True)
        raise

def extract_doc_id(url):
    """Extrait l'ID du document Google Docs depuis une URL."""
    if not isinstance(url, str):
        return None
    patterns = [r'/document/d/([a-zA-Z0-9-_]+)', r'/d/([a-zA-Z0-9-_]+)']
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            logger.debug(f"Document ID extrait: {match.group(1)}")
            return match.group(1)
    logger.warning(f"Impossible d'extraire l'ID de l'URL: {url}")
    return None

def utf16_length(s):
    """
    Calcule la longueur en unités de code UTF‑16 (compatible avec Google Docs).
    """
    return len(s.encode('utf-16-le')) // 2

def assemble_new_text_and_styles(parsed_blocks):
    """
    Parcourt les blocs parsés pour construire une chaîne unique (new_text)
    et un tableau de styles avec les positions (en unités UTF‑16).
    
    Retourne : (new_text, style_ranges)
    
    Chaque élément de style_ranges est un dict qui peut contenir :
      - start: position de début
      - end: position de fin
      - style: un identifiant de style :
          * "TITLE", "HEADING_1", "HEADING_2", "HEADING_3" pour des titres,
          * "BULLET" pour une ligne de liste (nous générerons une commande createParagraphBullets),
          * "CODE" pour un bloc de code (appliquer une police monospace).
    Pour les paragraphes non stylisés, aucun style n'est défini.
    """
    new_text = ""
    style_ranges = []
    current_offset = 0  # en unités UTF-16

    for block in parsed_blocks:
        block_type = block.get('type')
        # Pour extraire le texte d'un bloc, nous tentons de récupérer la clé 'raw', sinon 'text'
        def get_block_text(children):
            return ''.join(child.get('raw', child.get('text', '')) for child in children).strip()

        if block_type == 'heading':
            level = block.get('attrs', {}).get('level')
            text = get_block_text(block.get('children', []))
            # On ajoute deux sauts de ligne pour aérer
            block_text = text + "\n\n"
            start = current_offset
            length = utf16_length(block_text)
            current_offset += length
            new_text += block_text
            style_type = "NORMAL_TEXT"
            if level == 1:
                style_type = "TITLE"
            elif level == 2:
                style_type = "HEADING_1"
            elif level == 3:
                style_type = "HEADING_2"
            elif level == 4:
                style_type = "HEADING_3"
            style_ranges.append({
                "start": start,
                "end": current_offset,
                "style": style_type
            })
        elif block_type == 'paragraph':
            text = get_block_text(block.get('children', []))
            block_text = text + "\n\n"
            start = current_offset
            length = utf16_length(block_text)
            current_offset += length
            new_text += block_text
            # Pour les paragraphes, on peut laisser le style par défaut ou ajouter "NORMAL_TEXT" si souhaité.
        elif block_type == 'blank_line':
            block_text = "\n"
            new_text += block_text
            current_offset += utf16_length(block_text)
        elif block_type == 'list':
            # Pour chaque item, on le traite comme un paragraphe avec bullet.
            for item in block.get('children', []):
                if item.get('type') != 'list_item':
                    continue
                # On suppose que chaque list_item possède des enfants de type block_text
                text = get_block_text(item.get('children', []))
                block_text = text + "\n"
                start = current_offset
                length = utf16_length(block_text)
                current_offset += length
                new_text += block_text
                style_ranges.append({
                    "start": start,
                    "end": current_offset,
                    "style": "BULLET"
                })
            # Séparation après la liste
            block_text = "\n"
            new_text += block_text
            current_offset += utf16_length(block_text)
        elif block_type == 'block_code':
            text = block.get('text', '').strip()
            if not text.endswith("\n"):
                text += "\n"
            block_text = text + "\n"
            start = current_offset
            length = utf16_length(block_text)
            current_offset += length
            new_text += block_text
            style_ranges.append({
                "start": start,
                "end": current_offset,
                "style": "CODE"
            })
        elif block_type == 'thematic_break':
            # Pour une ligne horizontale, on insère simplement un saut de ligne
            block_text = "\n"
            new_text += block_text
            current_offset += utf16_length(block_text)
        else:
            # Autres blocs : insertion brute
            text = block.get('raw', str(block))
            block_text = text + "\n\n"
            new_text += block_text
            current_offset += utf16_length(block_text)

    return new_text, style_ranges

@format_doc_bp.route('/format-doc', methods=['POST'])
def format_doc():
    if not request.is_json:
        return jsonify({"error": "Request body must be JSON"}), 400
    data = request.json
    markdown_content = data.get("content")
    google_doc_url = data.get("doc_url")
    if not markdown_content or not google_doc_url:
        return jsonify({"error": "Missing 'content' or 'doc_url' in request body"}), 400

    logger.info(f"[format-doc] Contenu Markdown reçu:\n{markdown_content}")
    doc_id = extract_doc_id(google_doc_url)
    if not doc_id:
        logger.warning(f"URL invalide reçue: {google_doc_url}")
        return jsonify({"error": "Invalid Google Doc URL provided"}), 400
    logger.info(f"Target doc ID: {doc_id}")

    try:
        service = get_google_docs_service()
    except Exception as e:
        return jsonify({"error": f"Failed to authenticate Google Docs API: {e}"}), 500

    try:
        # Créer l'AST à partir du Markdown
        markdown_parser = mistune.create_markdown(renderer='ast')
        parsed_blocks = markdown_parser(markdown_content)
        logger.info(f"Markdown parsed into {len(parsed_blocks)} blocks.")
    except Exception as e:
        logger.error(f"Erreur lors du parsing du Markdown: {e}", exc_info=True)
        return jsonify({"error": f"Failed to parse Markdown: {e}"}), 400

    try:
        new_text, style_ranges = assemble_new_text_and_styles(parsed_blocks)
        logger.debug(f"Texte assemblé (UTF-16 length = {utf16_length(new_text)}):\n{new_text}")
        logger.debug(f"Plages de style générées:\n{json.dumps(style_ranges, indent=2)}")
    except Exception as e:
        logger.error(f"Erreur lors de l'assemblage du texte: {e}", exc_info=True)
        return jsonify({"error": f"Error assembling text: {e}"}), 500

    # Générer la requête d'insertion du texte complet à l'index 1
    requests_batch = []
    requests_batch.append({
        "insertText": {
            "location": {"index": 1},
            "text": new_text
        }
    })

    # Générer les requêtes de style pour chaque plage
    for item in style_ranges:
        start = item["start"] + 1  # puisque le texte est inséré à partir de l'index 1
        end = item["end"] + 1
        style = item["style"]
        if style == "BULLET":
            requests_batch.append({
                "createParagraphBullets": {
                    "range": {"startIndex": start, "endIndex": end},
                    "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE"
                }
            })
        elif style == "CODE":
            requests_batch.append({
                "updateTextStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "textStyle": {"weightedFontFamily": {"fontFamily": "Courier New"}},
                    "fields": "weightedFontFamily"
                }
            })
        elif style in ["TITLE", "HEADING_1", "HEADING_2", "HEADING_3"]:
            requests_batch.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "paragraphStyle": {"namedStyleType": style},
                    "fields": "namedStyleType"
                }
            })
        # Pour les paragraphes standard, on laisse le style par défaut.

    logger.debug("Requêtes finales envoyées:\n" + json.dumps(requests_batch, indent=2))

    try:
        logger.info(f"Envoi de {len(requests_batch)} requêtes à l'API Google Docs.")
        service.documents().batchUpdate(documentId=doc_id, body={"requests": requests_batch}).execute()
        message = "Contenu inséré en haut du document avec succès !"
    except Exception as e:
        error_details = str(e)
        if hasattr(e, 'content'):
            try:
                error_data = json.loads(e.content.decode('utf-8'))
                error_details = error_data.get('error', {}).get('message', str(e))
            except Exception:
                pass
        logger.error(f"Erreur lors de batchUpdate pour doc {doc_id}: {error_details}", exc_info=True)
        return jsonify({"error": f"Failed to update Google Doc: {error_details}"}), 500

    logger.info(f"Terminé pour doc ID: {doc_id}")
    return jsonify({"message": message, "doc_url": google_doc_url})
