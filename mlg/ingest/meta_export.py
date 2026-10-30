"""Import a Facebook "Download Your Information" export (HTML format) - media plus its context.

    python -m mlg.ingest.meta_export albums <zip>...                 # what is in the export
    python -m mlg.ingest.meta_export extract <zip>... --album NAME [--album NAME] [--limit N]
                                             [--videos N] [--out data/media/facebook]

Facebook strips capture dates from photos, but the export keeps what the person
wrote around them: album names and descriptions, post captions, places with
coordinates, and upload times. All of that is saved next to each extracted file
(table `context` in the ingest DB) and handed to the Perceive pass as context.
Upload time is a weak date (an old scan can be uploaded years later), so it
gets date_source "upload" and the model may still date the photo from content.
"""
from __future__ import annotations

import argparse
import html as htmllib
import re
import sqlite3
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from mlg.config import DATA
from mlg.ingest.scan import DB, connect, ingest_file, mark_duplicates

MEDIA_RE = re.compile(r'(?:src|href)="(your_facebook_activity/posts/media/[^"]+?\.(?:jpe?g|png|gif|webp|mp4|mov))"', re.I)
DATE_RE = re.compile(r"<footer[^>]*>.*?<div[^>]*>([A-Z][a-z]{2} \d{2}, \d{4} \d{1,2}:\d{2}:\d{2} [ap]m)</div>", re.S)
PLACE_RE = re.compile(r"Place:.*?<a[^>]*>([^<]+)</a>\s*\(([-\d.]+),\s*([-\d.]+)\)", re.S)
SECTION_RE = re.compile(r"<section[^>]*>(.*?)</section>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
NOISE = ("Click for video:", "Upload IP address", "Mobile uploads", "Timeline photos", "Profile pictures")


@dataclass
class MediaInfo:
    zip_path: str
    album: str = ""
    album_description: str = ""
    captions: list[str] = field(default_factory=list)
    place: str = ""
    lat: float | None = None
    lon: float | None = None
    uploaded: str = ""


def _text(fragment: str) -> str:
    return htmllib.unescape(TAG_RE.sub(" ", fragment.replace("<br />", "\n"))).strip()


def _date(s: str) -> str:
    return datetime.strptime(s, "%b %d, %Y %I:%M:%S %p").isoformat()


def _caption(section: str) -> str:
    """The person's own words in a section: the longest text block that isn't boilerplate."""
    body = re.sub(r"<footer[^>]*>.*?</footer>|<h2[^>]*>.*?</h2>|<table.*?</table>", "", section, flags=re.S)
    body = re.sub(r"Place:.*?\)", "", body, flags=re.S)
    blocks = [_text(b) for b in re.findall(r"<(?:span|div)[^>]*>([^<]*(?:<br />[^<]*)*)</(?:span|div)>", body)]
    blocks = [b for b in blocks if len(b) > 2 and not any(n in b for n in NOISE) and not b.startswith("http")]
    return max(blocks, key=len, default="")[:600]


def parse(zips: list[Path]) -> dict[str, MediaInfo]:
    media: dict[str, MediaInfo] = {}
    for zp in zips:
        zf = zipfile.ZipFile(zp)
        for name in zf.namelist():
            if not name.endswith(".html") or "/posts/" not in name and "tagged_in" not in name:
                continue
            page = zf.read(name).decode("utf-8", "replace")
            album = album_desc = ""
            if "/posts/album/" in name:
                if m := re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S):
                    album = _text(m.group(1))
                if m := re.search(r"</h1>\s*<p[^>]*>(.*?)</p>", page, re.S):
                    album_desc = _text(m.group(1))[:300]
            for sec in SECTION_RE.findall(page):
                paths = list(dict.fromkeys(MEDIA_RE.findall(sec)))
                if not paths:
                    continue
                cap = _caption(sec)
                place = PLACE_RE.search(sec)
                date = DATE_RE.search(sec)
                for p in paths:
                    info = media.setdefault(p, MediaInfo(p))
                    if album and not info.album:
                        info.album, info.album_description = album, album_desc
                    if cap and cap != info.album and cap not in info.captions:
                        info.captions.append(cap)
                    if place and not info.place:
                        info.place, info.lat, info.lon = _text(place.group(1)), float(place.group(2)), float(place.group(3))
                    if date and not info.uploaded:
                        info.uploaded = _date(date.group(1))
    return media


def _zip_for(zips: list[Path]) -> dict[str, zipfile.ZipFile]:
    where = {}
    for zp in zips:
        zf = zipfile.ZipFile(zp)
        for n in zf.namelist():
            where.setdefault(n, zf)
    return where


def save_context(con: sqlite3.Connection, path: Path, info: MediaInfo) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS context (path TEXT PRIMARY KEY, source TEXT, album TEXT,
                   album_description TEXT, captions TEXT, place TEXT, lat REAL, lon REAL, uploaded TEXT)""")
    con.execute("INSERT OR REPLACE INTO context VALUES (?,?,?,?,?,?,?,?,?)",
                (str(path), "facebook", info.album, info.album_description, "\n---\n".join(info.captions),
                 info.place, info.lat, info.lon, info.uploaded))


def extract(zips: list[Path], albums: list[str] | None, limit: int | None, videos: int, out: Path,
            db: Path = DB, progress=None) -> dict:
    """albums=None takes everything (the app's one-button import); a list takes those albums only."""
    media = parse(zips)
    where = _zip_for(zips)
    wanted = [m for m in media.values() if (albums is None or m.album in albums)
              and not m.zip_path.endswith((".mp4", ".mov"))]
    wanted.sort(key=lambda m: m.uploaded)
    if limit:
        wanted = wanted[:limit]
    vids = sorted((m for m in media.values() if m.zip_path.endswith((".mp4", ".mov"))
                   and (albums is None or m.captions)),
                  key=lambda m: m.uploaded, reverse=True)[:videos]
    con = connect(db)
    n = 0
    for info in wanted + vids:
        zf = where.get(info.zip_path)
        if zf is None:
            continue
        sub = re.sub(r"[^\w\-]+", "_", info.album or "videos").strip("_")[:40] or "misc"
        dest = out / sub / Path(info.zip_path).name
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(info.zip_path))
        save_context(con, dest, info)
        if ingest_file(con, dest) and info.uploaded:
            row = con.execute("SELECT date_source FROM items WHERE path=?", (str(dest),)).fetchone()
            if row and row["date_source"] == "mtime":
                con.execute("UPDATE items SET taken_at=?, date_source='upload' WHERE path=?",
                            (info.uploaded, str(dest)))
        n += 1
        if n % 25 == 0:
            con.commit()
            if progress:
                progress(n)
    con.commit()
    return {"extracted": n, "duplicates": mark_duplicates(con)}


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("albums")
    a.add_argument("zips", nargs="+", type=Path)
    e = sub.add_parser("extract")
    e.add_argument("zips", nargs="+", type=Path)
    e.add_argument("--album", action="append", default=[])
    e.add_argument("--limit", type=int)
    e.add_argument("--videos", type=int, default=0)
    e.add_argument("--out", type=Path, default=DATA / "media" / "facebook")
    args = ap.parse_args()
    if args.cmd == "albums":
        media = parse(args.zips)
        by: dict[str, list[MediaInfo]] = {}
        for m in media.values():
            by.setdefault(m.album or "(no album)", []).append(m)
        for album, items in sorted(by.items(), key=lambda kv: -len(kv[1])):
            dates = sorted(i.uploaded[:10] for i in items if i.uploaded)
            caps = sum(1 for i in items if i.captions)
            places = sum(1 for i in items if i.place)
            print(f"{len(items):5}  {dates[0] if dates else '?'}..{dates[-1] if dates else '?'}  "
                  f"captions {caps:4}  places {places:4}  {album}")
    else:
        print(extract(args.zips, args.album, args.limit, args.videos, args.out))


if __name__ == "__main__":
    main()
