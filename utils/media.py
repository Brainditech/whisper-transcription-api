"""Media input helpers: download URLs to a temp file, safe cleanup."""
from __future__ import annotations

import logging
import os
import tempfile
from typing import Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

DOWNLOAD_CONNECT_TIMEOUT = int(os.environ.get("WHISPER_DOWNLOAD_CONNECT_TIMEOUT", "15"))
DOWNLOAD_READ_TIMEOUT = int(os.environ.get("WHISPER_DOWNLOAD_TIMEOUT", "600"))
MAX_DOWNLOAD_SIZE = (
    int(os.environ.get("WHISPER_MAX_DOWNLOAD_SIZE_MB", "2048")) * 1024 * 1024
)


def download_to_temp(url: str) -> str:
    """Stream `url` to a temp file and return its absolute path.

    Raises `ValueError` on bad status or oversized payloads.
    """
    logger.info("Downloading media from %s", url)
    parsed = urlparse(url)
    ext = os.path.splitext(parsed.path)[1] or ".bin"

    fd, tmp_path = tempfile.mkstemp(suffix=ext)
    os.close(fd)

    total = 0
    try:
        with requests.get(
            url,
            stream=True,
            timeout=(DOWNLOAD_CONNECT_TIMEOUT, DOWNLOAD_READ_TIMEOUT),
            headers={"User-Agent": "whisper-transcription-api/1.0"},
            allow_redirects=True,
        ) as resp:
            if resp.status_code != 200:
                raise ValueError(
                    f"Download failed: HTTP {resp.status_code} for {url}"
                )
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_SIZE:
                        raise ValueError(
                            f"Download exceeded max size ({MAX_DOWNLOAD_SIZE} bytes)"
                        )
                    f.write(chunk)
        logger.info("Downloaded %d bytes to %s", total, tmp_path)
        return tmp_path
    except Exception:
        safe_remove(tmp_path)
        raise


def safe_remove(path: Optional[str]) -> None:
    if not path:
        return
    if not os.path.exists(path):
        return
    try:
        os.remove(path)
    except OSError as e:
        logger.warning("Failed to remove %s: %s", path, e)
