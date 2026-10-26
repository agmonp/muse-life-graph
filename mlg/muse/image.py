"""Muse Image: title cards, posters, chapter cards. Output is always marked generated."""
from __future__ import annotations

import base64
from pathlib import Path

from mlg.config import settings
from mlg.muse.http import MetaHTTP
from mlg.muse.media import image_data_url


def generate(prompt: str, out: Path, *, size: str = "1536x1024", references: list[Path] | None = None,
             fmt: str = "png", strength: str = "low") -> Path:
    """Text (+ optional reference photos) -> one image file at `out`."""
    http = MetaHTTP()
    if references:
        body = {"model": settings().image_model, "prompt": prompt, "n": 1, "size": size,
                "output_format": fmt, "reasoning_strength": strength,
                "images": [{"image_url": image_data_url(p)} for p in references[:10]]}
        reply = http.post("/images/edits", body)
    else:
        body = {"model": settings().image_model, "prompt": prompt, "n": 1, "size": size,
                "output_format": fmt, "reasoning_strength": strength}
        reply = http.post("/images/generations", body)
    data = reply.body["data"][0]["b64_json"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(data))
    return out
