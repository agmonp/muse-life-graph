"""Head-and-shoulders crop of one observed person, from a photo or a video keyframe."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from mlg.muse.media import open_image
from mlg.perceive.keyframes import keyframes


def person_crop(path: str | Path, kind: str, bbox: list | None, frame: int | None = None,
                head_only: bool = True, max_side: int = 512) -> Image.Image | None:
    """bbox is [x1,y1,x2,y2] on the 0-1000 grid; None when the face is too small to use."""
    if not bbox:
        return None
    path = Path(path)
    if kind == "video":
        frames = keyframes(path)
        if not frames:
            return None
        img = open_image(frames[min(frame or 0, len(frames) - 1)][1])
    elif kind == "photo":
        img = open_image(path)
    else:
        return None
    w, h = img.size
    x1, y1, x2, y2 = (list(bbox) + [0, 0, 1000, 1000])[:4]
    x1, x2 = sorted((x1 * w / 1000, x2 * w / 1000))
    y1, y2 = sorted((y1 * h / 1000, y2 * h / 1000))
    mx, my = (x2 - x1) * 0.1, (y2 - y1) * 0.1
    bottom = y1 + (y2 - y1) * 0.65 if head_only else y2
    box = (max(0, x1 - mx), max(0, y1 - my), min(w, x2 + mx), min(h, bottom + my))
    if box[2] - box[0] < 24 or box[3] - box[1] < 24:
        return None
    crop = img.crop(tuple(int(v) for v in box))
    crop.thumbnail((max_side, max_side))
    return crop
