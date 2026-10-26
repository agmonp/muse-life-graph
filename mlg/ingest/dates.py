"""When was this taken? EXIF > container metadata > filename > file mtime.

`source` says how much to trust the date. "mtime" is a guess only: copies,
WhatsApp forwards and scans all reset it, so the perceive pass may replace it
with a content-based estimate (film stock, clothes, print borders).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

EXIF_IFD = 0x8769
DATETIME_ORIGINAL, DATETIME_DIGITIZED, DATETIME = 36867, 36868, 306

# IMG_20190612_153012, VID-20190612-WA0003, 2019-06-12 15.30.12, PXL_20190612_..., Screenshot_20190612-...
NAME_PATTERNS = [
    re.compile(r"(?<!\d)(19[5-9]\d|20[0-4]\d)[-_]?(0[1-9]|1[0-2])[-_]?(0[1-9]|[12]\d|3[01])"
               r"(?:[-_ T.]?([01]\d|2[0-3])[-_.:]?([0-5]\d)[-_.:]?([0-5]\d)\d{0,3})?(?!\d)"),
]


def _parse_exif(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip()[:19], "%Y:%m:%d %H:%M:%S")
    except (ValueError, AttributeError):
        return None


def exif_date(path: Path) -> datetime | None:
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            sub = exif.get_ifd(EXIF_IFD)
            for tag in (DATETIME_ORIGINAL, DATETIME_DIGITIZED):
                if (d := _parse_exif(sub.get(tag))) and d.year > 1900:
                    return d
            if (d := _parse_exif(exif.get(DATETIME))) and d.year > 1900:
                return d
    except Exception:  # noqa: BLE001 - unreadable/odd formats just have no EXIF date
        return None
    return None


def container_date(path: Path) -> datetime | None:
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    r = subprocess.run([exe, "-v", "error", "-show_entries", "format_tags=creation_time",
                        "-of", "json", str(path)], capture_output=True, text=True)
    try:
        stamp = json.loads(r.stdout)["format"]["tags"]["creation_time"]
        d = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (KeyError, ValueError, json.JSONDecodeError):
        return None
    if d.year < 1971:  # 1970/1904 epoch defaults from cameras without a clock
        return None
    return d.astimezone(timezone.utc).replace(tzinfo=None)


def filename_date(path: Path) -> datetime | None:
    for pat in NAME_PATTERNS:
        if m := pat.search(path.stem):
            y, mo, d, hh, mm, ss = m.groups()
            try:
                return datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0), int(ss or 0))
            except ValueError:
                continue
    return None


def resolve(path: Path, kind: str) -> tuple[str, str]:
    """Return (ISO timestamp, source) where source is exif|container|filename|mtime."""
    if kind == "photo" and (d := exif_date(path)):
        return d.isoformat(), "exif"
    if kind in ("video", "audio") and (d := container_date(path)):
        return d.isoformat(), "container"
    if d := filename_date(path):
        return d.isoformat(), "filename"
    return datetime.fromtimestamp(path.stat().st_mtime).replace(microsecond=0).isoformat(), "mtime"
