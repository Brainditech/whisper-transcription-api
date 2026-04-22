# Whisper Transcription API

Production-ready REST API around [faster-whisper](https://github.com/SYSTRAN/faster-whisper),
tuned for **robust long-form transcription** (meetings, podcasts, multi-hour
recordings) on GPU.

## What's new in this revision

The previous version used to "drift" or hallucinate on audios longer than a
few minutes. This revision fixes that by adopting the modern long-form recipe:

- **`large-v3`** (configurable, also supports `large-v3-turbo` for ~8× speed).
- **VAD filter on by default** → silences are skipped, no more invented
  text during quiet passages.
- **`condition_on_previous_text=False`** → kills the runaway hallucination
  loop that occurs when Whisper's prior context is fed back in on long files.
- **Temperature fallback ladder** → automatic re-decoding when a window
  fails the compression / log-prob sanity checks.
- **Segments + timestamps** returned alongside the plain text.
- **Streaming endpoint** (NDJSON) — get segments as they're produced.
- **Async job endpoint** — submit huge files, poll for the result, never
  hold a long HTTP connection open.
- **SRT / VTT / text** output formats, in addition to JSON.
- **CUDA 12.4 + cuDNN 9** base image (required by faster-whisper 1.1+).
- **Pinned dependencies**, healthcheck, model cache volume, env-driven config.

The legacy `POST /transcribe` contract (`file` upload **or** `media_url`,
returns `{transcription, metadata}`) is preserved — the JSON response just
gained extra fields.

## Quick start

```bash
docker compose up -d --build
# first request triggers a one-off model download into the `whisper-models` volume
curl -X POST http://localhost:8000/transcribe \
  -F "file=@/path/to/audio.mp3" \
  -F "language=fr"
```

Or without compose:

```bash
docker build -t whisper-api .
docker run -d --gpus all -p 8000:8000 \
  -v whisper-models:/models \
  -e WHISPER_MODEL=large-v3 \
  --name whisper-api whisper-api
```

## Configuration

All settings are environment variables (see `.env.example` for the full list).
Key ones:

| Var | Default | Notes |
|-----|---------|-------|
| `WHISPER_MODEL` | `large-v3` | Or `large-v3-turbo`, `medium`, `small`, `distil-large-v3`, ... |
| `WHISPER_DEVICE` | `auto` | `cuda` / `cpu` / `auto` |
| `WHISPER_COMPUTE_TYPE` | `auto` | `float16` (GPU) / `int8` (CPU) / `int8_float16` |
| `WHISPER_DOWNLOAD_ROOT` | `/models` | Persist model cache via a volume |
| `WHISPER_PRELOAD` | `1` | Load model at boot, slower start, faster first request |
| `WHISPER_ASYNC_WORKERS` | `1` | Concurrent background transcriptions (each costs VRAM) |
| `MAX_UPLOAD_MB` | `2048` | multipart body limit |
| `WHISPER_MAX_DOWNLOAD_SIZE_MB` | `2048` | URL download limit |
| `WHISPER_DOWNLOAD_TIMEOUT` | `600` | URL read timeout (seconds) |
| `WAITRESS_CHANNEL_TIMEOUT` | `3600` | Long-request safety net |

## Endpoints

### `POST /transcribe` — synchronous

Form fields **or** JSON body:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `file` | file | — | Audio/video upload (multipart only) |
| `media_url` | string | — | Remote URL to download instead |
| `metadata` | string | — | Echoed back in the response |
| `language` | string | auto | Force a language (`fr`, `en`, ...). Improves quality + speed. |
| `task` | string | `transcribe` | Or `translate` (translate to English) |
| `vad_filter` | bool | `true` | Strongly recommended for long audio |
| `vad_min_silence_ms` | int | `500` | Silence threshold for VAD |
| `condition_on_previous_text` | bool | `false` | Set to `true` to restore the legacy (lossy) behavior |
| `beam_size` | int | `5` | Decoding beam |
| `temperature` | float | `0.0` | `0.0` enables the fallback ladder; any other value disables it |
| `word_timestamps` | bool | `false` | Per-word timings under each segment |
| `initial_prompt` | string | — | Lexicon hint (names, jargon) |
| `no_speech_threshold` | float | `0.6` | |
| `compression_ratio_threshold` | float | `2.4` | |
| `response_format` | string | `json` | `json` / `text` / `srt` / `vtt` |

Example:

```bash
curl -X POST http://localhost:8000/transcribe \
  -F "file=@meeting.mp4" \
  -F "language=fr" \
  -F "response_format=srt" \
  -o meeting.srt
```

JSON response:

```json
{
  "transcription": "...",
  "text": "...",
  "segments": [
    {"id": 0, "start": 0.0, "end": 4.32, "text": " ...", "avg_logprob": -0.21, "no_speech_prob": 0.01}
  ],
  "language": "fr",
  "language_probability": 0.99,
  "duration": 612.4,
  "duration_after_vad": 588.1,
  "model": "large-v3",
  "metadata": null
}
```

### `POST /transcribe/stream` — NDJSON stream

Same parameters as `/transcribe`. The connection stays open, but you receive
one JSON line per segment **as soon as it's produced** — useful for
progress UIs on long files.

```
{"type":"segment","id":0,"start":0.0,"end":4.32,"text":" ...","progress":0.007}
{"type":"segment","id":1,"start":4.32,"end":9.10,"text":" ...","progress":0.014}
...
{"type":"done","language":"fr","duration":612.4}
```

### `POST /transcribe/async` — background job

Same parameters; returns immediately:

```json
{"job_id": "9f2c...", "status": "queued"}
```

Then poll:

```bash
curl http://localhost:8000/jobs/9f2c...
curl http://localhost:8000/jobs/9f2c...?response_format=srt
```

### `GET /jobs` — list known jobs (in-memory)

### `GET /health`

```json
{"status":"ok","model":"large-v3","device":"cuda","compute_type":"float16"}
```

## Why long audios used to fail

faster-whisper inherits the OpenAI Whisper sliding-window decoder. With its
defaults:

1. Each 30-second window can hallucinate on silences (no VAD).
2. The decoded text of one window is fed as **prompt** to the next
   (`condition_on_previous_text=True`). One bad window can poison every
   subsequent window — the model gets stuck repeating the same phrase, or
   drifts off-topic for the rest of the file.

This API now defaults to **VAD on** + **prior-text off**. If you really
need the legacy behavior, pass `condition_on_previous_text=true` per-request.

## n8n workflow

The TikTok scraper workflow under `n8n_workflows/` still works — it posts a
binary file to `POST /transcribe` exactly like before. To get SRT subtitles
back instead, add `response_format=srt` to the form data.

## Project layout

```
whisper-transcription-api/
├── app.py                    Flask + Waitress entrypoint
├── Dockerfile                CUDA 12.4 + cuDNN 9 + ffmpeg
├── docker-compose.yml        GPU-aware compose file
├── requirements.txt          Pinned versions
├── .env.example              All env vars documented
├── blueprints/
│   └── transcribe.py         HTTP routes
├── utils/
│   ├── whisper_utils.py      Model singleton + transcription options
│   ├── media.py              URL download (timeouts, size cap)
│   ├── formatters.py         SRT / VTT / text
│   └── jobs.py               In-process async job queue
└── n8n_workflows/            Sample TikTok→transcript pipeline
```

## License

MIT — see `LICENSE`.
