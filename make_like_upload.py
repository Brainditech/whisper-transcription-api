from flask import Blueprint, request, jsonify
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import io
import logging
import json
import mistune  # si vous voulez convertir du Markdown en HTML

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

make_like_bp = Blueprint('make_like', __name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
SERVICE_ACCOUNT_FILE = "service_account.json"  # Ajustez vers votre JSON de compte de service

def get_drive_service():
    """Crée et retourne un service Google Drive authentifié."""
    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=SCOPES
        )
        service = build('drive', 'v3', credentials=credentials)
        logger.info("Service Google Drive authentifié avec succès.")
        return service
    except Exception as e:
        logger.error(f"Impossible de créer le service Drive : {e}", exc_info=True)
        raise

@make_like_bp.route('/upload-html-doc', methods=['POST'])
def upload_html_doc():
    """
    Reçoit du HTML (ou éventuellement du Markdown), crée un Google Doc formaté
    en uploadant le fichier via l’API Drive, comme le fait Make ou Zapier.
    
    Exemple de payload JSON :
      {
        "title": "Mon joli doc",
        "html": "<h1>Titre</h1><p>Paragraphe <strong>en gras</strong></p>"
      }
      
    Renvoie : { "docId": "...", "docUrl": "..." }
    """
    data = request.json
    if not data:
        return jsonify({"error": "Le body doit être en JSON"}), 400

    title = data.get("title", "Document généré via API")
    html_input = data.get("html")  # ou "markdown"

    if not html_input:
        return jsonify({"error": "Il manque le champ 'html' (ou du Markdown)."}), 400

    # Option 1 : si c'est du Markdown et que vous devez le convertir en HTML.
    # html_input = mistune.html(html_input)

    # Connexion Drive
    drive_service = get_drive_service()

    try:
        # On crée un buffer mémoire avec le HTML
        html_bytes = html_input.encode('utf-8')
        media_body = MediaIoBaseUpload(io.BytesIO(html_bytes), mimetype='text/html', resumable=False)

        # Méta-données : on indique qu’on veut un Document Google (mimeType = google-apps.document)
        file_metadata = {
            "name": title,
            "mimeType": "application/vnd.google-apps.document"
        }

        # On crée le fichier (import/conversion HTML -> Google Docs)
        created = drive_service.files().create(
            body=file_metadata,
            media_body=media_body,
            fields="id"
        ).execute()

        doc_id = created.get("id")
        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
        logger.info(f"Document créé : {doc_id}")

        return jsonify({
            "docId": doc_id,
            "docUrl": doc_url
        }), 200

    except Exception as e:
        logger.error(f"Erreur lors de l'upload HTML -> Doc : {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
