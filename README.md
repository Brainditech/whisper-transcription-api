# Whisper Transcription API

A robust, production-ready REST API wrapper for [faster-whisper](https://github.com/guillaumekln/faster-whisper), designed for high-performance audio and video transcription using GPU acceleration.

## 🚀 Features
- **Accurate & Fast:** Uses the `large-v2` model from `faster-whisper`.
- **Media Support:** Native support for transcribing both audio (`.mp3`, `.wav`) and video (`.mp4`) files seamlessly.
- **Flexible Endpoints:** Submit media files directly or via remote URLs.
- **Dockerized:** Containerized with NVIDIA CUDA dependencies for easy and consistent deployment.
- **Production-Ready:** Served via Waitress for robust concurrent request handling.

## 📋 Prerequisites
- Linux / Windows OS
- [Docker](https://docs.docker.com/get-docker/)
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) (for GPU support)
- NVIDIA GPU with at least 8GB of VRAM (due to `large-v2` model requirements; optimized using `float16` compute type).

---

## 🛠️ Setup & Installation

### 1. Clone the repository
```bash
git clone https://github.com/your-username/whisper-transcription-api.git
cd whisper-transcription-api
```

### 2. Build the Docker image
```bash
docker build -t whisper-api .
```

### 3. Run the Container
You need to pass the `--gpus all` flag to allow the container to access your NVIDIA GPU.
```bash
docker run -it --gpus all -p 8000:8000 whisper-api
```
The server will start on `http://localhost:8000`.

*(Note: The first time you make a transcription request, the Whisper model will be downloaded automatically. Subsequent requests will be much faster.)*

---

## 📡 API Reference

### Health Check
Verify the API is running.
- **URL:** `/health`
- **Method:** `GET`

**Response:**
```json
{
  "status": "ok"
}
```

### Transcribe Media File
Transcribe an audio or video file by uploading it directly.

- **URL:** `/transcribe`
- **Method:** `POST`
- **Content-Type:** `multipart/form-data`

**Request Parameters:**
- `file` (File, Required): The media file (e.g., .mp3, .mp4, .wav).
- `metadata` (String, Optional): Any custom metadata you want returned with the response.

**cURL Example:**
```bash
curl -X POST http://localhost:8000/transcribe \
  -F "file=@/path/to/your/audio.mp3" \
  -F "metadata=Test Recording 1"
```

### Transcribe via URL
Transcribe a media file hosted on a remote server.

- **URL:** `/transcribe`
- **Method:** `POST`
- **Content-Type:** `application/json`

**Request Body:**
```json
{
  "media_url": "https://example.com/path/to/media.mp4",
  "metadata": "Remote Video Transcription"
}
```

**cURL Example:**
```bash
curl -X POST http://localhost:8000/transcribe \
  -H "Content-Type: application/json" \
  -d '{"media_url": "https://example.com/audio.mp3", "metadata": "Sample Metadata"}'
```

**Success Response (200 OK):**
```json
{
  "transcription": "This is the transcribed text from the media file.",
  "metadata": "Test Recording 1"
}
```

---

## 🤖 Bonus: n8n Automation Workflow

An automated workflow for n8n is included in this repository to demonstrate a complete pipeline: **Downloading a TikTok video without third-party APIs and transcribing it automatically.**

### Included Workflow
- **File:** `n8n_workflows/TiktokTranscriptor.json`

### How it Works
1. **Trigger:** Accepts a TikTok URL via a web form.
2. **Scraping:** Fetches the page HTML and extracts the temporary session cookies and the concealed direct video URL (`playAddr`) from the TikTok JSON payload.
3. **Download:** Downloads the `.mp4` video directly to memory (binary data block) spoofing browser headers to bypass protections.
4. **Transcription:** Posts the binary file directly to this `faster-whisper` API payload endpoint (`/transcribe`).
5. **Output:** Returns a clean JSON format with the transcribed text.

### How to use it in n8n
1. Open your n8n workspace.
2. Go to **Workflows** -> **Add Workflow**.
3. Click the options menu (three dots) in the top right corner and select **Import from File**.
4. Select the `TiktokTranscriptor.json` file.
5. Make sure the HTTP Node `WhisperTranscribe` points to your correct Whisper API URL (e.g., `http://host.docker.internal:8000/transcribe` if n8n is in Docker on the same machine).
6. Click **Execute Workflow** or activate it to test with a TikTok URL!

---

## 🏗️ Project Structure
```text
whisper-transcription-api/
├── blueprints/
│   └── transcribe.py       # API endpoints and logic
├── utils/
│   └── whisper_utils.py    # Whisper model loading and inference
├── app.py                  # Flask setup and Waitress server
├── Dockerfile              # Docker configuration
├── requirements.txt        # Python dependencies
├── .dockerignore
└── .gitignore
```

## 📝 License
This project is licensed under the MIT License - see the `LICENSE` file for details.
