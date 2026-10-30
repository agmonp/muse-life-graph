"""The hosted site: the same app, reading copies of the owner's media instead of their disk.

On the owner's computer every media path in the graph is a real file. The hosted demo has
none of those files; `scripts/build_site_bundle.py` makes a reduced copy of each one, named
by a hash of the original path, and uploads them to the site's volume. `local(path)` maps an
original path to its copy when MLG_SITE_MEDIA is set and returns it unchanged otherwise, so
every reader goes through one function and the local app behaves exactly as before.

The site is a showcase of the owner's own graph: visitors browse, search, ask and make films,
but never change who is who (`read_only`), and the whole site sits behind an access code.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

MEDIA = os.environ.get("MLG_SITE_MEDIA")
CODE = os.environ.get("MLG_SITE_CODE")
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


def enabled() -> bool:
    return bool(MEDIA)


def copy_name(path: str) -> str:
    """The copy's file name: photos become .jpg, videos and audio keep their kind of extension."""
    p = Path(path)
    ext = ".jpg" if p.suffix.lower() in PHOTO_EXT else p.suffix.lower()
    return hashlib.md5(str(path).encode("utf-8")).hexdigest() + ext


def local(path: str | None) -> str | None:
    if not MEDIA or not path:
        return path
    return str(Path(MEDIA) / copy_name(path))
