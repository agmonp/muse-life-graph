"""Ingest a folder: hash every photo/video/audio, date it, fingerprint it, mark duplicates.

    python -m mlg.ingest.scan <folder> [--db data/cache/ingest.sqlite]

Re-runs are incremental (a file whose size+mtime is unchanged is skipped).
Duplicates are never deleted: each one gets `dup_of` = the keeper's path.
The keeper is the largest-resolution copy, then the one with the most trusted date.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from mlg.config import CACHE
from mlg.ingest import dates
from mlg.ingest.phash import PHOTO_MAX_DIST, VIDEO_MAX_DIST, hamming_matrix, photo_hash, video_hash
from mlg.muse.media import kind_of, open_image, probe_duration, sha256_file

DB = CACHE / "ingest.sqlite"
DATE_TRUST = {"exif": 0, "container": 1, "filename": 2, "content": 3, "mtime": 4}

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, kind TEXT NOT NULL, bytes INTEGER,
  mtime_ns INTEGER, width INTEGER, height INTEGER, duration_s REAL,
  taken_at TEXT, date_source TEXT, phash TEXT, vhash TEXT, dup_of TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS items_sha ON items(sha256);
"""


def connect(db: Path = DB) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _known(con: sqlite3.Connection, path: Path) -> bool:
    st = path.stat()
    row = con.execute("SELECT bytes, mtime_ns FROM items WHERE path=?", (str(path),)).fetchone()
    return bool(row) and row["bytes"] == st.st_size and row["mtime_ns"] == st.st_mtime_ns


def ingest_file(con: sqlite3.Connection, path: Path) -> str | None:
    kind = kind_of(path)
    if not kind or _known(con, path):
        return None
    st = path.stat()
    sha = sha256_file(path)
    rec = {"sha256": sha, "path": str(path), "kind": kind, "bytes": st.st_size,
           "mtime_ns": st.st_mtime_ns, "width": None, "height": None, "duration_s": None,
           "phash": None, "vhash": None, "error": None}
    try:
        if kind == "photo":
            img = open_image(path)
            rec["width"], rec["height"] = img.size
            rec["phash"] = f"{photo_hash(path):016x}"
        elif kind == "video":
            hashes, rec["duration_s"] = video_hash(path)
            rec["vhash"] = ",".join(f"{h:016x}" for h in hashes)
        else:
            rec["duration_s"] = probe_duration(path)
    except Exception as e:  # noqa: BLE001 - keep the row, flag it
        rec["error"] = f"{type(e).__name__}: {e}"[:300]
    rec["taken_at"], rec["date_source"] = dates.resolve(path, kind)
    cols = ",".join(rec)
    con.execute(f"INSERT OR REPLACE INTO items ({cols}, dup_of) VALUES ({','.join('?' * len(rec))}, NULL)",
                list(rec.values()))
    return sha


def _keeper_order(row: sqlite3.Row) -> tuple:
    px = (row["width"] or 0) * (row["height"] or 0)
    return (-px, -(row["duration_s"] or 0), DATE_TRUST.get(row["date_source"], 9), row["taken_at"] or "")


def _groups(rows: list[sqlite3.Row], hashes: list[list[int]], max_dist: int) -> list[list[int]]:
    """Union-find over items whose mean frame distance is within max_dist."""
    n = len(rows)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    width = min(len(h) for h in hashes) if hashes else 0
    if n < 2 or width == 0:
        return [[i] for i in range(n)]
    total = sum(hamming_matrix([h[k] for h in hashes]).astype(int) for k in range(width)) / width
    for i in range(n):
        for j in range(i + 1, n):
            if total[i, j] <= max_dist:
                if rows[i]["kind"] == "video":
                    di, dj = rows[i]["duration_s"] or 0, rows[j]["duration_s"] or 0
                    if abs(di - dj) > max(1.5, 0.05 * max(di, dj)):
                        continue
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def mark_duplicates(con: sqlite3.Connection) -> int:
    con.execute("UPDATE items SET dup_of=NULL")
    marked = 0
    for kind, col, max_dist in (("photo", "phash", PHOTO_MAX_DIST), ("video", "vhash", VIDEO_MAX_DIST)):
        rows = con.execute(f"SELECT * FROM items WHERE kind=? AND {col} IS NOT NULL AND {col}!=''",
                           (kind,)).fetchall()
        hashes = [[int(h, 16) for h in r[col].split(",")] for r in rows]
        for group in _groups(rows, hashes, max_dist):
            if len(group) < 2:
                continue
            members = sorted((rows[i] for i in group), key=_keeper_order)
            for dup in members[1:]:
                con.execute("UPDATE items SET dup_of=? WHERE path=?", (members[0]["path"], dup["path"]))
                marked += 1
    con.commit()
    return marked


def scan(folder: Path, db: Path = DB) -> dict:
    con = connect(db)
    new = 0
    # absolute paths: the web app and workers may run from another working directory
    for path in sorted(p for p in folder.resolve().rglob("*") if p.is_file()):
        if ingest_file(con, path):
            new += 1
            if new % 50 == 0:
                con.commit()
                print(f"  {new} new files", flush=True)
    con.commit()
    dups = mark_duplicates(con)
    stats = {r["kind"]: r["n"] for r in con.execute("SELECT kind, COUNT(*) n FROM items GROUP BY kind")}
    return {"new": new, "duplicates": dups, "by_kind": stats}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--db", type=Path, default=DB)
    a = ap.parse_args()
    print(scan(a.folder, a.db))


if __name__ == "__main__":
    main()
