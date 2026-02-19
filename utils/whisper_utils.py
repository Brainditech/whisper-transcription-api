import whisper
import torch
import os

device = "cuda" if torch.cuda.is_available() else "cpu"
model = whisper.load_model("large-v2", device=device)


def transcribe_audio_file(filepath):
    # Whisper gère nativement l'extraction audio depuis les fichiers vidéo via ffmpeg en interne
    # Pas besoin de créer un fichier mp3 intermédiaire sur le disque.
    try:
        if os.path.exists(filepath):
            return model.transcribe(filepath)["text"]
        else:
             raise FileNotFoundError(f"Fichier non trouvé: {filepath}")
    except Exception as e:
        raise RuntimeError(f"Erreur Whisper: {str(e)}")

