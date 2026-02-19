FROM pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y ffmpeg git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copier requirements
COPY requirements.txt .

RUN pip install --upgrade pip \
 && pip install -r requirements.txt

# 🚀 Ajouter ici : download modèle une bonne fois pour toutes
RUN python -c "import whisper; whisper.load_model('large-v2')"

# Copier tout le reste du code
COPY . .

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--timeout", "1200", "app:app"]