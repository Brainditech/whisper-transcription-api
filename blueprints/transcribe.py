"""HTTP endpoints for transcription.

Routes
------
POST /transcribe          → synchronous JSON / text / srt / vtt response
POST /transcribe/stream   → NDJSON stream of segments as they're produced
POST /transcribe/async    → enqueue, returns {job_id}
GET  /jobs/<id>           → job status / result (supports response_format)
GET  /jobs                → list known jobs
GET  /health              → liveness + model info
"""
from __future__ import annotations

import json as _json
import logging
import os
import tempfile
from typing import Any, Optional

from flask import Blueprint, Response, jsonify, request, stream_with_context

from utils.formatters import to_plaintext, to_srt, to_vtt
from utils.jobs import JobQueue
from utils.media import download_to_temp, safe_remove
from utils.whisper_utils import TranscribeOptions, WhisperService

logger = logging.getLogger(__name__)

transcribe_bp = Blueprint("transcribe", __name__)

_BOOL_TRUE = {"1", "true", "yes", "on"}

_job_queue: Optional[JobQueue] = None


def get_job_queue() -> JobQueue:
    global _job_queue
    if _job_queue is None:
        workers = int(os.environ.get("WHISPER_ASYNC_WORKERS", "1"))
        _job_queue = JobQueue(workers=workers)
    return _job_queue


# --- payload helpers -------------------------------------------------------

def _parse_bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in _BOOL_TRUE


def _collect_payload() -> dict:
    """Merge form data, JSON body and query string into a single dict."""
    data: dict = {}
    if request.form:
        data.update(request.form.to_dict(flat=True))
    if request.is_json:
        body = request.get_json(silent=True) or {}
        if isinstance(body, dict):
            for k, v in body.items():
                if k != "file":
                    data[k] = v
    if request.args:
        for k, v in request.args.items():
            data.setdefault(k, v)
    return data


def _opt(payload: dict, key: str, default=None, cast=None):
    v = payload.get(key, default)
    if v is None or v == "":
        return default
    if cast is not None:
        try:
            return cast(v)
        except (TypeError, ValueError):
            return default
    return v


def _parse_options(payload: dict) -> TranscribeOptions:
    return TranscribeOptions(
        language=_opt(payload, "language"),
        task=_opt(payload, "task", "transcribe"),
        beam_size=_opt(payload, "beam_size", 5, int),
        temperature=_opt(payload, "temperature", 0.0, float),
        vad_filter=_parse_bool(payload.get("vad_filter"), True),
        vad_min_silence_ms=_opt(payload, "vad_min_silence_ms", 500, int),
        word_timestamps=_parse_bool(payload.get("word_timestamps"), False),
        initial_prompt=_opt(payload, "initial_prompt"),
        condition_on_previous_text=_parse_bool(
            payload.get("condition_on_previous_text"), False
        ),
        no_speech_threshold=_opt(payload, "no_speech_threshold", 0.6, float),
        compression_ratio_threshold=_opt(
            payload, "compression_ratio_threshold", 2.4, float
        ),
        log_prob_threshold=_opt(payload, "log_prob_threshold", -1.0, float),
    )


def _prepare_input_file(payload: dict) -> str:
    if "file" in request.files:
        f = request.files["file"]
        suffix = os.path.splitext(f.filename or "")[1] or ".bin"
        fd, tmp_filepath = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        f.save(tmp_filepath)
        logger.info("Saved upload to %s", tmp_filepath)
        return tmp_filepath

    url = payload.get("media_url") or payload.get("url")
    if url:
        return download_to_temp(url)

    raise ValueError(
        "No file or URL provided. Send multipart 'file' or JSON body with 'media_url'."
    )


def _format_response(result: dict, fmt: str, metadata):
    fmt = (fmt or "json").lower()
    segments = result.get("segments", [])
    if fmt == "json":
        return jsonify(
            {
                # Backward-compat: older clients expect `transcription`.
                "transcription": result.get("text", ""),
                "text": result.get("text", ""),
                "segments": segments,
                "language": result.get("language"),
                "language_probability": result.get("language_probability"),
                "duration": result.get("duration"),
                "duration_after_vad": result.get("duration_after_vad"),
                "model": result.get("model"),
                "metadata": metadata,
            }
        )
    if fmt == "text":
        return Response(to_plaintext(segments), mimetype="text/plain; charset=utf-8")
    if fmt == "srt":
        return Response(to_srt(segments), mimetype="application/x-subrip; charset=utf-8")
    if fmt == "vtt":
        return Response(to_vtt(segments), mimetype="text/vtt; charset=utf-8")
    return jsonify({"error": f"Unknown response_format '{fmt}'"}), 400


# --- routes ----------------------------------------------------------------

@transcribe_bp.route("/transcribe", methods=["POST"])
def transcribe():
    tmp_filepath = None
    try:
        payload = _collect_payload()
        metadata = payload.get("metadata")
        response_format = payload.get("response_format", "json")
        options = _parse_options(payload)
        tmp_filepath = _prepare_input_file(payload)

        logger.info(
            "Sync transcription start (lang=%s, vad=%s, cond_prev=%s, beam=%d)",
            options.language, options.vad_filter,
            options.condition_on_previous_text, options.beam_size,
        )
        result = WhisperService.instance().transcribe(tmp_filepath, options)
        logger.info(
            "Sync transcription done: %d segments, duration=%s, lang=%s",
            len(result.get("segments", [])),
            result.get("duration"), result.get("language"),
        )
        return _format_response(result, response_format, metadata)

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.exception("Transcription failed")
        return jsonify({"error": str(e)}), 500
    finally:
        safe_remove(tmp_filepath)


@transcribe_bp.route("/transcribe/stream", methods=["POST"])
def transcribe_stream():
    """Stream segments as NDJSON: one JSON object per line.

    The connection stays open for the whole transcription, but the
    client receives progress events as soon as each segment lands.
    """
    tmp_filepath = None
    try:
        payload = _collect_payload()
        options = _parse_options(payload)
        tmp_filepath = _prepare_input_file(payload)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        safe_remove(tmp_filepath)
        logger.exception("Failed to prepare streaming transcription")
        return jsonify({"error": str(e)}), 500

    service = WhisperService.instance()
    path = tmp_filepath

    def gen():
        try:
            total_duration: Optional[float] = None
            for seg in service.transcribe_iter(path, options):
                if total_duration is None and service.last_info:
                    total_duration = service.last_info.duration
                event = {
                    "type": "segment",
                    "id": seg.id,
                    "start": seg.start,
                    "end": seg.end,
                    "text": seg.text,
                    "progress": (seg.end / total_duration) if total_duration else None,
                }
                yield _json.dumps(event, ensure_ascii=False) + "\n"
            info = service.last_info
            yield _json.dumps(
                {
                    "type": "done",
                    "language": info.language if info else None,
                    "language_probability": info.language_probability if info else None,
                    "duration": info.duration if info else None,
                },
                ensure_ascii=False,
            ) + "\n"
        except Exception as e:
            logger.exception("Streaming transcription failed")
            yield _json.dumps(
                {"type": "error", "error": str(e)}, ensure_ascii=False
            ) + "\n"
        finally:
            safe_remove(path)

    return Response(stream_with_context(gen()), mimetype="application/x-ndjson")


@transcribe_bp.route("/transcribe/async", methods=["POST"])
def transcribe_async():
    """Enqueue a transcription and return a job id immediately.

    Useful for very long audios where keeping the HTTP connection open
    is impractical. Poll GET /jobs/<id> to retrieve the result.
    """
    tmp_filepath = None
    try:
        payload = _collect_payload()
        metadata = payload.get("metadata")
        options = _parse_options(payload)
        response_format = payload.get("response_format", "json")
        tmp_filepath = _prepare_input_file(payload)
    except ValueError as e:
        safe_remove(tmp_filepath)
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        safe_remove(tmp_filepath)
        logger.exception("Failed to prepare async job")
        return jsonify({"error": str(e)}), 500

    service = WhisperService.instance()
    path = tmp_filepath  # captured in closure; cleaned after run() exits

    def run(job):
        try:
            result = service.transcribe(path, options)
            job.duration_seconds = result.get("duration")
            job.progress_seconds = result.get("duration")
            return {
                "text": result.get("text"),
                "segments": result.get("segments"),
                "language": result.get("language"),
                "language_probability": result.get("language_probability"),
                "duration": result.get("duration"),
                "duration_after_vad": result.get("duration_after_vad"),
                "model": result.get("model"),
                "response_format": response_format,
            }
        finally:
            safe_remove(path)

    job = get_job_queue().submit(run, metadata=metadata)
    return jsonify({"job_id": job.id, "status": job.status}), 202


@transcribe_bp.route("/jobs/<job_id>", methods=["GET"])
def job_status(job_id: str):
    job = get_job_queue().get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404

    fmt = (request.args.get("response_format") or "json").lower()
    if (
        job.status == "done"
        and fmt != "json"
        and isinstance(job.result, dict)
        and "segments" in job.result
    ):
        segs = job.result["segments"]
        if fmt == "text":
            return Response(to_plaintext(segs), mimetype="text/plain; charset=utf-8")
        if fmt == "srt":
            return Response(to_srt(segs), mimetype="application/x-subrip; charset=utf-8")
        if fmt == "vtt":
            return Response(to_vtt(segs), mimetype="text/vtt; charset=utf-8")
    return jsonify(job.to_dict())


@transcribe_bp.route("/jobs", methods=["GET"])
def jobs_list():
    return jsonify([j.to_dict() for j in get_job_queue().list_jobs()])


@transcribe_bp.route("/health", methods=["GET"])
def health():
    try:
        svc = WhisperService.instance()
        return jsonify(
            {
                "status": "ok",
                "model": svc.model_name,
                "device": svc.device,
                "compute_type": svc.compute_type,
            }
        )
    except Exception as e:
        logger.exception("Health check failed")
        return jsonify({"status": "error", "error": str(e)}), 503
