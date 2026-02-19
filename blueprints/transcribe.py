from flask import Blueprint, request, jsonify
import tempfile, os
from utils.whisper_utils import transcribe_audio_file
import requests
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

transcribe_bp = Blueprint('transcribe', __name__)

@transcribe_bp.route('/transcribe', methods=['POST'])
def transcribe():
    # Définition de tmp_filepath avant le try pour garantir son existence dans le finally
    tmp_filepath = None
    
    try:
        # Récupère metadata (facultatif)
        metadata = request.form.get('metadata')
        
        # 1. Si fichier binaire fourni
        if 'file' in request.files:
            file = request.files['file']
            # On utilise delete=False car on veut fermer le fichier avant de le passer à whisper
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
                file.save(tmp.name)
                tmp_filepath = tmp.name
                logger.info(f"Fichier reçu et sauvegardé temporairement : {tmp_filepath}")

        # 2. Si URL fournie
        elif request.json and 'media_url' in request.json:
            url = request.json['media_url']
            logger.info(f"Téléchargement depuis l'URL : {url}")
            resp = requests.get(url, stream=True)
            if resp.status_code == 200:
                # On essaie de deviner l'extension depuis l'URL, sinon par défaut .tmp
                ext = os.path.splitext(url)[1]
                if not ext: ext = ".tmp"
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                    for chunk in resp.iter_content(chunk_size=8192):
                        tmp.write(chunk)
                    tmp_filepath = tmp.name
                logger.info(f"Fichier téléchargé : {tmp_filepath}")
            else:
                logger.error(f"Échec du téléchargement : {resp.status_code}")
                return jsonify({"error": "Failed to download media_url"}), 400
        else:
            return jsonify({'error': 'No file or URL provided'}), 400

        # Transcription
        logger.info("Démarrage de la transcription...")
        transcription = transcribe_audio_file(tmp_filepath)
        logger.info("Transcription terminée avec succès.")

        # Reponse simple, tu peux renvoyer metadata aussi
        return jsonify({
            "transcription": transcription,
            "metadata": metadata
        })

    except Exception as e:
        logger.error(f"Erreur lors de la transcription : {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

    finally:
        # Nettoyage du fichier temporaire dans tous les cas
        if tmp_filepath and os.path.exists(tmp_filepath):
            try:
                os.remove(tmp_filepath)
                logger.info(f"Fichier temporaire supprimé : {tmp_filepath}")
            except OSError as e:
                logger.warning(f"Impossible de supprimer le fichier temporaire {tmp_filepath}: {e}")

# ✅ Ajout de la route /health
@transcribe_bp.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200