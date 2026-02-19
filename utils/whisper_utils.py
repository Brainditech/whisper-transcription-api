import whisper
import torch
import subprocess
import os

device = "cuda" if torch.cuda.is_available() else "cpu"
model = whisper.load_model("large-v2", device=device)


def transcribe_audio_file(filepath):
    # Liste des extensions vidéo courantes qui nécessitent une extraction audio
    video_extensions = {".mp4", ".mov", ".mkv", ".avi", ".ts", ".webm", ".flv", ".wmv"}
    ext = os.path.splitext(filepath)[1].lower()
    
    if ext in video_extensions:
        mp3_path = filepath + ".mp3"
        subprocess.run([
            "ffmpeg", "-y", "-i", filepath,
            "-vn",
            "-acodec", "libmp3lame",
            "-ar", "16000",
            "-ac", "1",
            mp3_path
        ], check=True)
        filepath = mp3_path

    if os.path.getsize(filepath) == 0:
        raise ValueError("Aucun audio trouvé")

    return model.transcribe(filepath)["text"]

