"""ffmpeg and ffprobe: next to the downloadable app (its ffmpeg/ folder), from MLG_FFMPEG_DIR, or on PATH."""
from __future__ import annotations

import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=2)
def _find(name: str) -> str | None:
    dirs = [os.environ.get("MLG_FFMPEG_DIR")]
    if getattr(sys, "frozen", False):
        dirs.append(str(Path(sys.executable).parent / "ffmpeg"))
    for d in filter(None, dirs):
        for exe in (Path(d) / f"{name}.exe", Path(d) / name):
            if exe.exists():
                return str(exe)
    return shutil.which(name)


def ffmpeg() -> str | None:
    return _find("ffmpeg")


def ffprobe() -> str | None:
    return _find("ffprobe")
