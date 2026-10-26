"""Checks that need no API key or database."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFilter

from mlg.ingest import dates
from mlg.ingest.scan import scan
from mlg.muse.sam import _parse
from mlg.perceive.schema import Perception, strict_schema

SAM_SAMPLE = (
    "<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334|>"
    "<|mask;x=0;y=0;data=27,60,~!!!!M!0c[0o91w?q1!pIH4pPRVp2B3'7`e.ioeAf6-k/#Xd8%dX9x(|>"
    ",1<|box;x1=155;y1=228;x2=202;y2=254;w=320;h=334|>"
    "<|mask;x=0;y=0;data=27,48,~!!!!J!0c[q=Pj_zs=*4C4(/./x#:/`S_GnD`=o3?X{emCgO$y@|>\n"
)


def _walk(node, fn):
    fn(node)
    if isinstance(node, dict):
        for v in node.values():
            _walk(v, fn)
    elif isinstance(node, list):
        for v in node:
            _walk(v, fn)


def test_strict_schema_rules():
    sch = strict_schema()
    text = json.dumps(sch)
    assert "$ref" not in text and "$defs" not in text
    assert sch["type"] == "object"

    def check(n):
        if isinstance(n, dict):
            assert "allOf" not in n and "oneOf" not in n
            if n.get("type") == "object" and "properties" in n:
                assert n["additionalProperties"] is False
                assert set(n["required"]) == set(n["properties"])
    _walk(sch, check)


def test_schema_accepts_minimal_perception():
    ev = {"bbox": [10, 10, 500, 900], "t": None, "frame": None, "cue": "smiling"}
    data = {
        "media_id": "abc",
        "scene": {"summary": "A birthday.",
                  "setting": {"indoor": False, "place_type": "garden", "place_name": None,
                              "evidence": [ev], "confidence": 0.8},
                  "date": {"estimate": "1994", "source": "content", "rationale": "film grain", "confidence": 0.5},
                  "event_guess": {"type": "birthday", "title": "70th", "rationale": "cake", "confidence": 0.9}},
        "people": [], "objects": [], "activities": [], "utterances": [],
        "edges": [{"type": "EVOKED_EMOTION", "source": "scene", "target": "joy",
                   "props": {"kind": None, "valence": 0.9, "intensity": 0.8, "role": None},
                   "basis": "observed", "evidence": [ev], "rationale": "everyone laughs", "confidence": 0.9}],
        "open_questions": [],
    }
    assert Perception.model_validate(data).edges[0].target == "joy"


def test_sam_parser_two_objects_with_masks():
    segs = _parse(SAM_SAMPLE, is_video=True)
    assert {s.object_id for s in segs} == {"0", "1"}
    first = next(s for s in segs if s.object_id == "0")
    assert first.box == (211, 228, 271, 255)  # inclusive wire corners -> half-open
    raster = first.raster()
    assert len(raster) == 27 * 60 and set(raster) <= {0, 1}


def _scene(seed: int) -> Image.Image:
    img = Image.new("RGB", (800, 600), (40 * seed % 255, 120, 200))
    d = ImageDraw.Draw(img)
    for i in range(12):
        x = (i * 97 * (seed + 3)) % 700
        d.ellipse((x, (i * 53 * seed) % 500, x + 90, (i * 53 * seed) % 500 + 90),
                  fill=((i * 40) % 255, (seed * 70) % 255, 30))
    return img


def test_perceptual_dedup(tmp_path: Path):
    a = _scene(1)
    a.save(tmp_path / "IMG_20190612_153012.jpg", quality=95)
    a.resize((400, 300)).filter(ImageFilter.GaussianBlur(0.6)).save(tmp_path / "IMG-20190612-WA0001.jpg", quality=55)
    _scene(2).save(tmp_path / "other.png")
    out = scan(tmp_path, tmp_path / "t.sqlite")
    assert out["duplicates"] == 1
    import sqlite3
    con = sqlite3.connect(tmp_path / "t.sqlite")
    keeper, dup = con.execute("SELECT dup_of, path FROM items WHERE dup_of IS NOT NULL").fetchone()
    assert keeper.endswith("IMG_20190612_153012.jpg") and dup.endswith("WA0001.jpg")


def test_video_dedup_reencode(tmp_path: Path):
    import subprocess
    src = tmp_path / "frames.png"
    _scene(3).save(src)
    a, b = tmp_path / "VID_20200101_120000.mp4", tmp_path / "VID-20200101-WA0002.mp4"
    base = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(src), "-t", "4",
            "-vf", "zoompan=z='zoom+0.004':d=1:s=640x480:fps=25", "-pix_fmt", "yuv420p"]
    subprocess.run(base + [str(a)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(a), "-vf", "scale=320:-2",
                    "-crf", "38", str(b)], check=True)
    src.unlink()
    assert scan(tmp_path, tmp_path / "v.sqlite")["duplicates"] == 1


@pytest.mark.parametrize("name,expected", [
    ("IMG_20190612_153012", "2019-06-12T15:30:12"),
    ("VID-20211231-WA0003", "2021-12-31T00:00:00"),
    ("PXL_20230101_101010123", "2023-01-01T10:10:10"),
    ("2018-07-04 18.22.01", "2018-07-04T18:22:01"),
])
def test_filename_dates(name, expected):
    assert dates.filename_date(Path(name + ".jpg")).isoformat() == expected


def test_no_date_in_plain_name():
    assert dates.filename_date(Path("IMG_1234.jpg")) is None
