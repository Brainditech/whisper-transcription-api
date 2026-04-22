import os
import logging

from flask import Flask

from blueprints.transcribe import transcribe_bp

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("whisper-api")


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def create_app() -> Flask:
    app = Flask(__name__)
    max_mb = int(os.environ.get("MAX_UPLOAD_MB", "2048"))
    app.config["MAX_CONTENT_LENGTH"] = max_mb * 1024 * 1024
    app.json.ensure_ascii = False

    app.register_blueprint(transcribe_bp)

    if _env_bool("WHISPER_PRELOAD", True):
        from utils.whisper_utils import WhisperService
        try:
            WhisperService.instance()
        except Exception as e:
            logger.error("Failed to preload Whisper model: %s", e, exc_info=True)

    return app


app = create_app()


if __name__ == "__main__":
    from waitress import serve

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    threads = int(os.environ.get("WAITRESS_THREADS", "4"))
    channel_timeout = int(os.environ.get("WAITRESS_CHANNEL_TIMEOUT", "3600"))

    logger.info(
        "Starting Waitress on %s:%d (threads=%d, channel_timeout=%ds)",
        host, port, threads, channel_timeout,
    )
    serve(app, host=host, port=port, threads=threads, channel_timeout=channel_timeout)
