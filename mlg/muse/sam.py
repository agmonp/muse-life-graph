"""SAM 3.1 segmentation through /v1/responses, parsed with Meta's meta-sam-parser.

One concept per call ("person", "birthday cake"). Returns per-object boxes in
source pixels and lazily decoded masks.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from meta_sam_parser import (CompletedOutcome, SegmentationBoxRecord, SegmentationMask,
                             SegmentationMaskRecord, decode_mask_to_raster,
                             image_segmentation_format, video_segmentation_format)

from mlg.config import settings
from mlg.muse import cache
from mlg.muse.chat import _responses_text
from mlg.muse.files import upload
from mlg.muse.http import MetaHTTP
from mlg.muse.media import image_data_url, sha256_file, to_mp4


@dataclass
class Segment:
    object_id: str
    frame: int | None
    box: tuple[float, float, float, float]  # left, top, right, bottom (px, half-open)
    confidence: float | None
    mask: SegmentationMask | None = None

    def raster(self) -> bytes:
        """Row-major 0/1 bytes of mask.height * mask.width."""
        return decode_mask_to_raster(self.mask)


def _parse(raw: str, is_video: bool) -> list[Segment]:
    fmt = video_segmentation_format() if is_video else image_segmentation_format()
    parser = fmt.create_parser()
    list(parser.push(raw if raw.endswith("\n") else raw + "\n"))
    result = parser.finish(CompletedOutcome()).result
    segs: dict[tuple, Segment] = {}
    for rec in result.records:
        frame = rec.frame.frame_index if getattr(rec, "frame", None) else None
        k = (rec.object_id, frame) if hasattr(rec, "object_id") else None
        if isinstance(rec, SegmentationBoxRecord):
            segs[k] = Segment(rec.object_id, frame, (rec.left, rec.top, rec.right, rec.bottom),
                              rec.confidence)
        elif isinstance(rec, SegmentationMaskRecord) and k in segs:
            segs[k].mask = rec.mask
    return list(segs.values())


def segment(media: Path, concept: str, *, confidence: bool = True, use_cache: bool = True) -> list[Segment]:
    is_video = media.suffix.lower() in {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".3gp", ".webm"}
    http = MetaHTTP()
    key = cache.key_for({"sam": sha256_file(media), "c": concept, "conf": confidence})
    raw = cache.get(key) if use_cache else None
    if raw is None:
        part = ({"type": "input_video", "file_id": upload(to_mp4(media), http)} if is_video
                else {"type": "input_image", "image_url": image_data_url(media, 2048)})
        body = {"model": settings().sam_model,
                "input": [{"type": "message", "role": "user",
                           "content": [{"type": "input_text", "text": concept}, part]}],
                "metadata": {"include_confidence": "true" if confidence else "false"}}
        reply = http.post("/responses", body)
        raw = _responses_text(reply.body)
        cache.put(key, raw)
    return _parse(raw, is_video) if raw else []
