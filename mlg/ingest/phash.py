"""Perceptual fingerprints: pHash for photos, three-frame pHash for videos.

Byte equality misses WhatsApp/Google re-encodes, resizes and burst shots, so
duplicates are found by Hamming distance between 64-bit perceptual hashes.
"""
from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

import imagehash
import numpy as np
from PIL import Image

from mlg.muse.media import open_image, probe_duration

PHOTO_MAX_DIST = 8     # out of 64 bits; re-encodes land at 0-4, bursts at ~4-8
VIDEO_MAX_DIST = 10    # mean over the three sampled frames


def photo_hash(path: Path) -> int:
    return int(str(imagehash.phash(open_image(path))), 16)


def _frame_at(path: Path, t: float) -> Image.Image | None:
    exe = shutil.which("ffmpeg")
    r = subprocess.run([exe, "-v", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                        "-vf", "scale=256:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
                       capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return None
    return Image.open(io.BytesIO(r.stdout)).convert("RGB")


def video_hash(path: Path) -> tuple[list[int], float | None]:
    """pHash of frames at 10%, 50%, 90% of the clip, plus its duration."""
    dur = probe_duration(path)
    times = [dur * f for f in (0.1, 0.5, 0.9)] if dur else [0.0]
    hashes = []
    for t in times:
        if (img := _frame_at(path, t)) is not None:
            hashes.append(int(str(imagehash.phash(img)), 16))
    return hashes, dur


def hamming_matrix(hashes: list[int]) -> np.ndarray:
    """All-pairs Hamming distance for 64-bit ints (fine up to ~20k items)."""
    a = np.array(hashes, dtype=np.uint64)
    out = np.empty((len(a), len(a)), dtype=np.uint8)
    for i in range(0, len(a), 1024):
        x = np.bitwise_xor(a[i:i + 1024, None], a[None, :])
        out[i:i + 1024] = np.unpackbits(x.view(np.uint8).reshape(*x.shape, 8), axis=-1).sum(-1)
    return out
