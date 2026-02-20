import requests
import os

# Configuration
url = "http://127.0.0.1:8000/transcribe"
# Utilisation du fichier test.mp4 déjà présent dans le dossier
file_path = "Dupersoncerveai.mp4" 

if not os.path.exists(file_path):
    print(f"Erreur: Le fichier de test {file_path} n'existe pas.")
    exit(1)

print(f"Envoi du fichier {file_path} vers {url}...")

with open(file_path, 'rb') as f:
    files = {'file': f}
    try:
        response = requests.post(url, files=files)
        
        if response.status_code == 200:
            print("\n✅ Succès ! Transcription reçue :")
            print("-" * 50)
            print(response.json().get('transcription', 'Pas de transcription trouvée'))
            print("-" * 50)
        else:
            print(f"\n❌ Erreur {response.status_code} :")
            print(response.text)
            
    except requests.exceptions.ConnectionError:
        print("\n❌ Impossible de se connecter au serveur. Assurez-vous qu'il est lancé (python app.py).")
