"""Whisper model service wrapper.

Singleton that owns the faster-whisper model and exposes a rich
transcription API with sane defaults for long-form audio:

- VAD filter enabled (skips silences → fewer hallucinations)
- condition_on_previous_text=False by default (prevents the
  hallucination loop that wrecks transcripts of long audio)
- Temperature fallback enabled
- Returns segments (with timestamps) alongside the concatenated text
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from typing import Any, Iterator, List, Optional

from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v if v is not None and v != "" else default


def _detect_cuda_count() -> int:
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0


def _resolve_device(device: str) -> str:
    if device and device != "auto":
        return device
    return "cuda" if _detect_cuda_count() > 0 else "cpu"


def _resolve_compute_type(compute_type: str, device: str) -> str:
    if compute_type and compute_type != "auto":
        return compute_type
    return "float16" if device == "cuda" else "int8"


@dataclass
class TranscribeOptions:
    """Tunables for a single transcription call.

    Defaults are chosen for robustness on long audio (several minutes
    to hours). Callers can override any field.
    """

    language: Optional[str] = None
    task: str = "transcribe"  # or "translate"
    beam_size: int = 5
    # If 0.0 we expand to the standard fallback ladder. Any other value is used as-is.
    temperature: float = 0.0
    vad_filter: bool = True
    vad_min_silence_ms: int = 500
    word_timestamps: bool = False
    initial_prompt: Optional[str] = None
    # KEY: False prevents Whisper's long-audio hallucination loops.
    condition_on_previous_text: bool = False
    no_speech_threshold: float = 0.6
    compression_ratio_threshold: float = 2.4
    log_prob_threshold: float = -1.0


@dataclass
class Segment:
    id: int
    start: float
    end: float
    text: str
    avg_logprob: Optional[float] = None
    no_speech_prob: Optional[float] = None
    compression_ratio: Optional[float] = None
    words: Optional[List[dict]] = None


@dataclass
class TranscribeInfo:
    language: Optional[str] = None
    language_probability: Optional[float] = None
    duration: Optional[float] = None
    duration_after_vad: Optional[float] = None


class WhisperService:
    """Lazy-loaded singleton around `faster_whisper.WhisperModel`."""

    _instance: Optional["WhisperService"] = None

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        download_root: Optional[str] = None,
        cpu_threads: Optional[int] = None,
        num_workers: Optional[int] = None,
    ) -> None:
        self.model_name = model_name or _env("WHISPER_MODEL", "large-v3")
        requested_device = device or _env("WHISPER_DEVICE", "auto")
        self.device = _resolve_device(requested_device)
        self.compute_type = _resolve_compute_type(
            compute_type or _env("WHISPER_COMPUTE_TYPE", "auto"),
            self.device,
        )
        self.download_root = download_root or _env("WHISPER_DOWNLOAD_ROOT", "")
        self.cpu_threads = (
            int(_env("WHISPER_CPU_THREADS", "0")) if cpu_threads is None else cpu_threads
        )
        self.num_workers = (
            int(_env("WHISPER_NUM_WORKERS", "1")) if num_workers is None else num_workers
        )

        logger.info(
            "Loading Whisper model '%s' (device=%s, compute_type=%s, download_root=%s)",
            self.model_name, self.device, self.compute_type, self.download_root or "<default>",
        )
        self.model = WhisperModel(
            self.model_name,
            device=self.device,
            compute_type=self.compute_type,
            download_root=self.download_root or None,
            cpu_threads=self.cpu_threads,
            num_workers=self.num_workers,
        )
        self._last_info: Optional[TranscribeInfo] = None
        logger.info("Whisper model loaded.")

    @classmethod
    def instance(cls) -> "WhisperService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def last_info(self) -> Optional[TranscribeInfo]:
        return self._last_info

    def _build_kwargs(self, opts: TranscribeOptions) -> dict:
        vad_parameters = None
        if opts.vad_filter:
            vad_parameters = {"min_silence_duration_ms": opts.vad_min_silence_ms}

        # Temperature fallback ladder (Whisper paper default). Triggered
        # when the primary decoding fails the compression/logprob checks.
        if opts.temperature is None or opts.temperature == 0.0:
            temperature: Any = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
        else:
            temperature = opts.temperature

        return dict(
            language=opts.language,
            task=opts.task,
            beam_size=opts.beam_size,
            temperature=temperature,
            vad_filter=opts.vad_filter,
            vad_parameters=vad_parameters,
            word_timestamps=opts.word_timestamps,
            initial_prompt=opts.initial_prompt,
            condition_on_previous_text=opts.condition_on_previous_text,
            no_speech_threshold=opts.no_speech_threshold,
            compression_ratio_threshold=opts.compression_ratio_threshold,
            log_prob_threshold=opts.log_prob_threshold,
        )

    def transcribe_iter(
        self, filepath: str, options: Optional[TranscribeOptions] = None
    ) -> Iterator[Segment]:
        opts = options or TranscribeOptions()
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        segments, info = self.model.transcribe(filepath, **self._build_kwargs(opts))
        self._last_info = TranscribeInfo(
            language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", None),
            duration=getattr(info, "duration", None),
            duration_after_vad=getattr(info, "duration_after_vad", None),
        )
        for seg in segments:
            words = None
            if opts.word_timestamps and getattr(seg, "words", None):
                words = [
                    {
                        "start": w.start,
                        "end": w.end,
                        "word": w.word,
                        "probability": getattr(w, "probability", None),
                    }
                    for w in seg.words
                ]
            yield Segment(
                id=seg.id,
                start=float(seg.start) if seg.start is not None else 0.0,
                end=float(seg.end) if seg.end is not None else 0.0,
                text=seg.text,
                avg_logprob=getattr(seg, "avg_logprob", None),
                no_speech_prob=getattr(seg, "no_speech_prob", None),
                compression_ratio=getattr(seg, "compression_ratio", None),
                words=words,
            )

    def transcribe(
        self, filepath: str, options: Optional[TranscribeOptions] = None
    ) -> dict:
        collected: List[Segment] = list(self.transcribe_iter(filepath, options))
        info = self._last_info
        text = "".join(s.text for s in collected).strip()
        return {
            "text": text,
            "segments": [asdict(s) for s in collected],
            "language": info.language if info else None,
            "language_probability": info.language_probability if info else None,
            "duration": info.duration if info else None,
            "duration_after_vad": info.duration_after_vad if info else None,
            "model": self.model_name,
        }


# --- Backward-compatible helper used by earlier versions -------------------

def transcribe_audio_file(filepath: str) -> str:
    """Legacy helper kept for backward compatibility."""
    return WhisperService.instance().transcribe(filepath)["text"]
