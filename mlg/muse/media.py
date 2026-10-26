"""Prepare local media for the API: resized JPEG data URLs, 16 kHz mono WAV, MP4."""
from __future__ import annotations

import base64
import hashlib
import io
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageOps

from mlg.config import CACHE

CONVERTED = CACHE / "converted"
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".bmp", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".3gp", ".webm", ".mts"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".ogg", ".opus", ".aac", ".flac", ".amr", ".wma"}


def kind_of(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        return "photo"
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def open_image(path: Path) -> Image.Image:
    img = Image.open(path)
    return ImageOps.exif_transpose(img).convert("RGB")


def jpeg_bytes(img: Image.Image, max_side: int = 1568, quality: int = 88) -> bytes:
    img = img.copy()
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def image_data_url(path_or_img: Path | Image.Image, max_side: int = 1568) -> str:
    img = path_or_img if isinstance(path_or_img, Image.Image) else open_image(path_or_img)
    return "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes(img, max_side)).decode()


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found on PATH")
    return exe


def _converted(src: Path, tag: str, ext: str) -> Path:
    digest = hashlib.sha256(f"{src.resolve()}|{src.stat().st_mtime_ns}|{tag}".encode()).hexdigest()[:24]
    CONVERTED.mkdir(parents=True, exist_ok=True)
    return CONVERTED / f"{digest}{ext}"


def to_wav(src: Path, rate: int = 16000, start: float | None = None, duration: float | None = None) -> Path:
    """Mono 16-bit PCM WAV - the format Voice Transcribe requires and Spark accepts."""
    out = _converted(src, f"wav{rate}-{start}-{duration}", ".wav")
    if not out.exists():
        cmd = [_ffmpeg(), "-y", "-loglevel", "error"]
        if start is not None:
            cmd += ["-ss", str(start)]
        cmd += ["-i", str(src)]
        if duration is not None:
            cmd += ["-t", str(duration)]
        cmd += ["-vn", "-ac", "1", "-ar", str(rate), "-c:a", "pcm_s16le", "-map_metadata", "-1", str(out)]
        subprocess.run(cmd, check=True)
    return out


def audio_b64(src: Path) -> str:
    return base64.b64encode(to_wav(src).read_bytes()).decode()


def to_mp4(src: Path, max_height: int = 720) -> Path:
    """H.264/AAC MP4, capped height - the only video container the API lists."""
    out = _converted(src, f"mp4{max_height}", ".mp4")
    if not out.exists():
        subprocess.run([_ffmpeg(), "-y", "-loglevel", "error", "-i", str(src),
                        "-vf", f"scale=-2:'min({max_height},ih)'", "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "26", "-c:a", "aac", "-b:a", "96k",
                        "-movflags", "+faststart", str(out)], check=True)
    return out


def probe_duration(src: Path) -> float | None:
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    r = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=nw=1:nk=1", str(src)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None
