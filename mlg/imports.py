"""Bring the owner's own media in: a folder on this computer, or a Facebook / Instagram export.

The files stay where they are (a folder is read in place; an export is unpacked
once into data/media/<source>). Each import is one background job the app can
show: find files -> fingerprint and drop duplicates -> wait for the owner's go
(Muse costs money, so the app shows the count and the estimate first) -> Muse
looks at every new item -> titles for the memories.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from mlg.config import DATA
from mlg.ingest.scan import connect, ingest_file, mark_duplicates
from mlg.muse.media import kind_of

COST = {"photo": 0.006, "video": 0.03, "audio": 0.02}   # measured $ per item (docs/PROBE_FINDINGS.md)
SECONDS = {"photo": 4.0, "video": 25.0, "audio": 15.0}
WORKERS = 6
JOB: dict = {"state": "idle"}
_LOCK = threading.Lock()


# ---------------- native pickers (the app runs on the owner's own computer) ----------------

_PICK = r"""
import sys, tkinter as tk
from tkinter import filedialog
root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True)
if sys.argv[1] == 'folder':
    print(filedialog.askdirectory(title='Choose the folder with your photos and videos') or '')
else:
    print('\n'.join(filedialog.askopenfilenames(title='Choose your Facebook or Instagram export (.zip)',
                                               filetypes=[('Export', '*.zip')])))
"""


def pick(what: str) -> list[str]:
    r = subprocess.run([sys.executable, "-c", _PICK, what], capture_output=True, text=True, timeout=600)
    return [line for line in r.stdout.splitlines() if line.strip()]


# ---------------- the job ----------------

def status() -> dict:
    with _LOCK:
        return dict(JOB)


def _set(**kw) -> None:
    with _LOCK:
        JOB.update(kw)


def _busy() -> bool:
    return JOB.get("state") in ("finding", "unpacking", "looking")


def _waiting_items() -> list[dict]:
    """Items fingerprinted but not yet seen by Muse."""
    from mlg.perceive.run import OUT
    con = connect()
    rows = con.execute("SELECT * FROM items WHERE dup_of IS NULL AND error IS NULL ORDER BY taken_at").fetchall()
    return [dict(r) for r in rows if not (OUT / f"{r['sha256']}.json").exists()
            and "data\\demo" not in r["path"] and "data/demo" not in r["path"]]


def estimate() -> dict:
    items = _waiting_items()
    by = {k: sum(1 for i in items if i["kind"] == k) for k in COST}
    return {"items": len(items), "by_kind": by, "dollars": round(sum(COST[k] * n for k, n in by.items()), 2),
            "minutes": round(sum(SECONDS[k] * n for k, n in by.items()) / WORKERS / 60, 1)}


def _after_find(source: str, found: int, dups: int) -> None:
    _set(state="ready", source=source, found=found, duplicates=dups, estimate=estimate(), finished=time.time())


def start_folder(folder: str) -> dict:
    p = Path(folder)
    if not p.is_dir():
        raise ValueError(f"folder not found: {folder}")
    if _busy():
        raise RuntimeError("an import is already running")

    def run():
        try:
            _set(state="finding", source=str(p), done=0, total=0, started=time.time(), error=None)
            files = [f for f in p.resolve().rglob("*") if f.is_file() and kind_of(f)]
            _set(total=len(files))
            con = connect()
            for n, f in enumerate(files, 1):
                ingest_file(con, f)
                if n % 25 == 0:
                    con.commit()
                    _set(done=n)
            con.commit()
            _set(done=len(files), state="finding", step="duplicates")
            _after_find(str(p), len(files), mark_duplicates(con))
        except Exception as e:  # noqa: BLE001 - shown in the app
            _set(state="failed", error=f"{type(e).__name__}: {e}")
    threading.Thread(target=run, daemon=True).start()
    time.sleep(0.2)
    return status()


# ---------------- Meta exports ----------------

def _which(zf: zipfile.ZipFile) -> str | None:
    names = zf.namelist()
    if any("your_facebook_activity/" in n for n in names):
        return "facebook"
    if any(n.startswith(("media/posts/", "your_instagram_activity/")) or "/media/posts/" in n
           or "instagram" in n.lower() for n in names):
        return "instagram"
    return None


IG_MEDIA = re.compile(r"(?:^|/)media/(?:posts|stories|reels|archived_posts|other)/[^/]+/[^/]+\.(?:jpe?g|png|heic|webp|mp4|mov)$", re.I)


def _instagram(zips: list[Path], out: Path) -> int:
    """Instagram 'Download your information' (JSON or HTML): every post, reel and story file, dated from
    the export's own timestamps when present (else the YYYYMM folder), captions kept as context."""
    con = connect()
    con.execute("""CREATE TABLE IF NOT EXISTS context (path TEXT PRIMARY KEY, source TEXT, album TEXT,
                   album_description TEXT, captions TEXT, place TEXT, lat REAL, lon REAL, uploaded TEXT)""")
    n = 0
    for zp in zips:
        zf = zipfile.ZipFile(zp)
        meta: dict[str, dict] = {}
        for name in zf.namelist():
            if not name.endswith(".json") or "/content/" not in name and "media" not in name:
                continue
            try:
                doc = json.loads(zf.read(name).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
            posts = doc if isinstance(doc, list) else next((v for v in doc.values() if isinstance(v, list)), []) \
                if isinstance(doc, dict) else []
            for post in posts:
                if not isinstance(post, dict):
                    continue
                for media in post.get("media", [post]):
                    if not isinstance(media, dict) or not media.get("uri"):
                        continue
                    ts = media.get("creation_timestamp") or post.get("creation_timestamp")
                    title = media.get("title") or post.get("title") or ""
                    meta[media["uri"].split("/", 1)[-1] if media["uri"].startswith("/") else media["uri"]] = {
                        "when": datetime.fromtimestamp(ts, timezone.utc).isoformat()[:19] if ts else "",
                        "caption": title.encode("latin-1", "ignore").decode("utf-8", "ignore") or title}
        for name in zf.namelist():
            if not IG_MEDIA.search(name):
                continue
            rel = name[name.find("media/"):]
            dest = out / rel.replace("media/", "", 1)
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(name))
            info = meta.get(rel) or meta.get(name) or {}
            when = info.get("when") or ""
            if not when and (m := re.search(r"/(\d{4})(\d{2})/", rel)):
                when = f"{m.group(1)}-{m.group(2)}-15T12:00:00"
            con.execute("INSERT OR REPLACE INTO context VALUES (?,?,?,?,?,?,?,?,?)",
                        (str(dest), "instagram", "Instagram " + rel.split("/")[1], "", info.get("caption", ""),
                         "", None, None, when))
            if ingest_file(con, dest) and when:
                row = con.execute("SELECT date_source FROM items WHERE path=?", (str(dest),)).fetchone()
                if row and row["date_source"] == "mtime":
                    con.execute("UPDATE items SET taken_at=?, date_source='upload' WHERE path=?", (when, str(dest)))
            n += 1
            if n % 25 == 0:
                con.commit()
                _set(done=n)
    con.commit()
    return n


def start_meta(paths: list[str]) -> dict:
    zips = [Path(p) for p in paths if p.lower().endswith(".zip") and Path(p).is_file()]
    if not zips:
        raise ValueError("choose the .zip files you downloaded from Facebook or Instagram")
    if _busy():
        raise RuntimeError("an import is already running")

    def run():
        try:
            _set(state="unpacking", source=", ".join(z.name for z in zips), done=0, total=0, started=time.time(),
                 error=None)
            kinds: dict[str, list[Path]] = {}
            for z in zips:
                with zipfile.ZipFile(z) as zf:
                    k = _which(zf)
                if k:
                    kinds.setdefault(k, []).append(z)
            if not kinds:
                raise ValueError("these files don't look like a Facebook or Instagram export")
            found = 0
            if "facebook" in kinds:
                from mlg.ingest import meta_export
                media = meta_export.parse(kinds["facebook"])
                _set(total=len(media), step="facebook")
                r = meta_export.extract(kinds["facebook"], None, None, 10**6, DATA / "media" / "facebook",
                                        progress=lambda n: _set(done=n))
                found += r["extracted"]
            if "instagram" in kinds:
                _set(step="instagram", done=0)
                found += _instagram(kinds["instagram"], DATA / "media" / "instagram")
            _after_find(", ".join(kinds), found, mark_duplicates(connect()))
        except Exception as e:  # noqa: BLE001 - shown in the app
            _set(state="failed", error=f"{type(e).__name__}: {e}")
    threading.Thread(target=run, daemon=True).start()
    time.sleep(0.2)
    return status()


# ---------------- Muse looks ----------------

def start_looking(limit: int | None = None) -> dict:
    if _busy():
        raise RuntimeError("an import is already running")
    items = _waiting_items()[:limit] if limit else _waiting_items()

    def run():
        from mlg import library
        from mlg.people import roster
        from mlg.perceive.run import perceive_item
        _set(state="looking", done=0, total=len(items), failed=0, started=time.time(), error=None)
        people = roster("real")
        with ThreadPoolExecutor(WORKERS) as ex:
            futs = [ex.submit(perceive_item, it, people) for it in items]
            for f in as_completed(futs):
                try:
                    f.result()
                except Exception:  # noqa: BLE001 - one bad file must not stop the rest
                    with _LOCK:
                        JOB["failed"] = JOB.get("failed", 0) + 1
                with _LOCK:
                    JOB["done"] = JOB.get("done", 0) + 1
        library.invalidate()
        _set(step="titles")
        try:
            library.write_titles()
        except Exception as e:  # noqa: BLE001 - titles are a nicety
            _set(error=f"titles: {e}")
        _set(state="done", finished=time.time())
    threading.Thread(target=run, daemon=True).start()
    time.sleep(0.2)
    return status()
