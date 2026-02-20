FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y ffmpeg git python3 python3-pip && rm -rf /var/lib/apt/lists/*

# Rediriger dynamiquement `python` et `pip` vers python3
RUN ln -sf /usr/bin/python3 /usr/bin/python && ln -sf /usr/bin/pip3 /usr/bin/pip

WORKDIR /app

# Copier requirements
COPY requirements.txt .

RUN pip install --upgrade pip \
    && pip install -r requirements.txt



# Copier tout le reste du code
COPY . .

EXPOSE 8000

CMD ["python", "app.py"]