"""Output formatters: plain text, SRT, VTT."""
from __future__ import annotations

from typing import Iterable, Mapping


def _fmt_timestamp(seconds: float, comma: bool = False) -> str:
    if seconds is None or seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    sep = "," if comma else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{ms:03d}"


def to_srt(segments: Iterable[Mapping]) -> str:
    lines = []
    for i, s in enumerate(segments, 1):
        text = (s.get("text") or "").strip()
        if not text:
            continue
        lines.append(str(i))
        lines.append(
            f"{_fmt_timestamp(s.get('start', 0.0), comma=True)} --> "
            f"{_fmt_timestamp(s.get('end', 0.0), comma=True)}"
        )
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def to_vtt(segments: Iterable[Mapping]) -> str:
    lines = ["WEBVTT", ""]
    for s in segments:
        text = (s.get("text") or "").strip()
        if not text:
            continue
        lines.append(
            f"{_fmt_timestamp(s.get('start', 0.0))} --> "
            f"{_fmt_timestamp(s.get('end', 0.0))}"
        )
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def to_plaintext(segments: Iterable[Mapping]) -> str:
    return "".join(s.get("text", "") for s in segments).strip()
