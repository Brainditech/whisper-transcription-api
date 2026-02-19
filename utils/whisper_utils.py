from faster_whisper import WhisperModel
import torch
import os

device = "cuda" if torch.cuda.is_available() else "cpu"
# Utiliser float16 si CUDA est disponible pour réduire la conso VRAM de moitié
compute_type = "float16" if device == "cuda" else "int8"
model = WhisperModel("large-v2", device=device, compute_type=compute_type)

def transcribe_audio_file(filepath):
    # Whisper gère nativement l'extraction audio depuis les fichiers vidéo via ffmpeg en interne
    # Pas besoin de créer un fichier mp3 intermédiaire sur le disque.
    try:
        if os.path.exists(filepath):
            segments, info = model.transcribe(filepath, beam_size=5)
            # Concaténer tous les segments de texte
            text = "".join([segment.text for segment in segments])
            return text.strip()
        else:
             raise FileNotFoundError(f"Fichier non trouvé: {filepath}")
    except Exception as e:
        raise RuntimeError(f"Erreur Whisper: {str(e)}")
