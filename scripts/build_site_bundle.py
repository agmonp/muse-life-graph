"""Build the hosted demo's files: a reduced copy of every media item in the graph, plus caches and films.

    python scripts/build_site_bundle.py [--films film_a film_b ...]
    python -m modal volume put mlg-site data/site_bundle /

Photos become JPEGs with a 1600 px long side (EXIF rotation applied), videos 720p H.264, voice notes
are copied as they are; every person's reference faces are copied too. Each copy is named by
`mlg.site.copy_name(original path)`, which is how the site finds it. Re-runs only add what is new.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mlg import site  # noqa: E402
from mlg.config import CACHE, DATA  # noqa: E402
from mlg.graph.db import session  # noqa: E402
from mlg.muse.media import open_image  # noqa: E402

OUT = DATA / "site_bundle"
MEDIA = OUT / "media"


def copy_one(path: str, kind: str) -> str:
    src, dst = Path(path), MEDIA / site.copy_name(path)
    if dst.exists():
        return "kept"
    if not src.exists():
        return "missing"
    tmp = dst.with_name(dst.stem + ".part" + dst.suffix)
    if kind == "photo":
        img = open_image(src).convert("RGB")
        img.thumbnail((1600, 1600))
        img.save(tmp, "JPEG", quality=85)
    elif kind == "video":
        subprocess.run([shutil.which("ffmpeg"), "-y", "-v", "error", "-i", str(src), "-vf", "scale=-2:'min(720,ih)'",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-c:a", "aac", "-b:a", "96k",
                        "-movflags", "+faststart", str(tmp)], check=True)
    else:
        shutil.copy(src, tmp)
    tmp.replace(dst)
    return "made"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--films", nargs="*", default=[], help="film ids to include (data/films/<id>)")
    a = ap.parse_args()
    MEDIA.mkdir(parents=True, exist_ok=True)
    with session() as s:
        items = s.run("MATCH (mi:MediaItem) RETURN mi.path AS path, mi.kind AS kind").data()
        crops = s.run("MATCH (p:Person {confirmed: true}) RETURN [c IN [p.ref_crop] + coalesce(p.ref_crops, []) "
                      "WHERE c IS NOT NULL] AS crops").data()
    jobs = [(i["path"], i["kind"]) for i in items if i["path"]] + \
           [(c, "photo") for r in crops for c in r["crops"]]
    counts: dict[str, int] = {}
    with ThreadPoolExecutor(6) as ex:
        for n, res in enumerate(ex.map(lambda j: copy_one(*j), jobs), 1):
            counts[res] = counts.get(res, 0) + 1
            if n % 250 == 0:
                print(f"{n}/{len(jobs)} {counts}", flush=True)
    print("media", counts, flush=True)
    data = OUT / "data" / "cache"
    data.mkdir(parents=True, exist_ok=True)
    for name in ("memory_titles.json", "faces.sqlite", "circle_names.json"):
        if (CACHE / name).exists():
            shutil.copy(CACHE / name, data / name)
    # the ingest database carries album names, captions and the owner's identity answers; a clean copy via backup
    src = sqlite3.connect(CACHE / "ingest.sqlite")
    dst = sqlite3.connect(data / "ingest.sqlite")
    src.backup(dst)
    dst.close()
    src.close()
    for fid in a.films:
        f = DATA / "films" / fid
        if f.exists():
            shutil.copytree(f, OUT / "data" / "films" / fid, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("*.part", "frames"))
    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file()) / 1e9
    print(f"bundle {OUT}: {size:.2f} GB")


if __name__ == "__main__":
    main()
