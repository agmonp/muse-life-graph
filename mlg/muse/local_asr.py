"""Speech to text on this computer, for the local and mixed modes: nothing is sent anywhere.

Uses faster-whisper (Whisper small, multilingual, Hebrew included) when it is installed; the model is
downloaded once into the shared Hugging Face cache. Without it, sound is left out and the app says so - a
recording is never quietly sent to the cloud instead.
"""
from __future__ import annotations

import importlib.util
from functools import lru_cache
from pathlib import Path

MODEL = "small"


def available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


@lru_cache(maxsize=1)
def _model():
    from faster_whisper import WhisperModel
    try:
        return WhisperModel(MODEL, device="cuda", compute_type="int8_float16")
    except Exception:  # noqa: BLE001 - no CUDA build or no GPU: the CPU is slower but works
        return WhisperModel(MODEL, device="cpu", compute_type="int8")


def segments(src: Path) -> list[tuple[float, float, str]]:
    """(start s, end s, text) for each spoken segment."""
    segs, _ = _model().transcribe(str(src), vad_filter=True)
    return [(s.start, s.end, s.text.strip()) for s in segs if s.text.strip()]
