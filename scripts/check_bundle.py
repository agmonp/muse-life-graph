"""Refuse to ship a build that carries anything personal: keys, the owner's data, faces, media.

    python scripts/check_bundle.py <built app folder or .zip> [--env .env]

Fails (exit 1) on: any settings or key file (.env, settings.env, site_code.txt), any database, cache or
usage log of the app, any photo, video or audio file outside the libraries' own small assets, and - when a
.env is given (a local build) - any of its secret values found in any file, as text or bytes.
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

NAMES = {".env", "settings.env", "site_code.txt", "usage.jsonl", "faces.sqlite", "ingest.sqlite",
         "memory_titles.json", "circle_names.json", "lifegraph_photo_people.json", "evals.json",
         "spark_open_eval.json", "answers.json", "storyboard.json", "state.json"}
DB_EXT = {".sqlite", ".sqlite3", ".db"}
MEDIA_EXT = {".jpg", ".jpeg", ".heic", ".heif", ".webp", ".mp4", ".mov", ".m4v", ".3gp", ".wav", ".mp3", ".m4a",
             ".ogg", ".opus", ".amr"}
# image assets shipped inside third-party libraries (checked by hand); everything else that is media fails
LIB_MEDIA_OK = ("_internal/PIL/", "_internal/tkinter/", "_internal/_tcl_data/", "_internal/_tk_data/",
                "_internal/tcl", "_internal/tk")
MAX_SCAN = 300 * 1024 * 1024


def entries(target: Path):
    if target.suffix.lower() == ".zip":
        with zipfile.ZipFile(target) as z:
            for i in z.infolist():
                if not i.is_dir():
                    yield i.filename.replace("\\", "/"), (lambda i=i: z.read(i))
    else:
        for p in target.rglob("*"):
            if p.is_file():
                yield p.relative_to(target).as_posix(), (lambda p=p: p.read_bytes())


def secrets(env: Path) -> list[bytes]:
    out = []
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if len(v) >= 12 and any(w in k.upper() for w in ("KEY", "PASSWORD", "TOKEN", "SECRET", "URI", "CODE")):
                out.append(v.encode())
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--env", help="a .env whose secret values must not appear anywhere in the build")
    a = ap.parse_args()
    target = Path(a.target)
    hidden = secrets(Path(a.env)) if a.env and Path(a.env).exists() else []
    site_code = Path(__file__).resolve().parent.parent / "data" / "site_code.txt"
    if site_code.exists() and len(code := site_code.read_text(encoding="utf-8").strip()) >= 6:
        hidden.append(code.encode())
    bad, n = [], 0
    for name, read in entries(target):
        n += 1
        low = name.lower()
        base = low.rsplit("/", 1)[-1]
        ext = "." + base.rsplit(".", 1)[-1] if "." in base else ""
        if base in NAMES:
            bad.append(f"personal file: {name}")
        elif ext in DB_EXT:
            bad.append(f"database: {name}")
        elif ext in MEDIA_EXT and not any(m.lower() in low for m in LIB_MEDIA_OK):
            bad.append(f"media: {name}")
        elif "/data/people/" in low or "/data/media/" in low or "/data/films/" in low:
            bad.append(f"owner data: {name}")
        if hidden:
            blob = read()
            if len(blob) <= MAX_SCAN and any(h in blob for h in hidden):
                bad.append(f"a secret value from {a.env} inside: {name}")
    print(f"checked {n} files in {target}" + (f", {len(hidden)} secret values searched" if hidden else ""))
    if bad:
        print("REFUSED:\n  " + "\n  ".join(bad[:50]))
        sys.exit(1)
    print("clean: no keys, no personal data, no media")


if __name__ == "__main__":
    main()
