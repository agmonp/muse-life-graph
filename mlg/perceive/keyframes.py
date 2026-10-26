"""Keyframes + audio track for a video: the shape Muse perceives videos in.

The probe showed native video input ignores the audio track, while keyframe
images plus an audio part in one Chat call are both understood.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from mlg.config import CACHE
from mlg.muse.media import probe_duration, sha256_file, to_wav

FRAMES = CACHE / "keyframes"
MAX_AUDIO_S = 300


def has_audio(path: Path) -> bool:
    r = subprocess.run([shutil.which("ffprobe"), "-v", "error", "-select_streams", "a",
                        "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return bool(r.stdout.strip())


def keyframes(path: Path, max_frames: int = 8, every_s: float = 3.0, width: int = 768) -> list[tuple[float, Path]]:
    """Evenly spaced frames (one per `every_s`, 3..max_frames), cached by content hash."""
    dur = probe_duration(path) or 0.0
    n = max(3, min(max_frames, round(dur / every_s))) if dur > 1 else 1
    times = [dur * (i + 0.5) / n for i in range(n)]
    out_dir = FRAMES / sha256_file(path)[:24]
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, t in enumerate(times):
        out = out_dir / f"f{i:02d}_{t:07.2f}.jpg"
        if not out.exists():
            subprocess.run([shutil.which("ffmpeg"), "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(path),
                            "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "3", str(out)], check=True)
        if out.exists():
            frames.append((round(t, 2), out))
    return frames


def audio_track(path: Path) -> Path | None:
    if not has_audio(path):
        return None
    return to_wav(path, 16000, None, MAX_AUDIO_S if (probe_duration(path) or 0) > MAX_AUDIO_S else None)
