"""Files API uploads, remembered by content hash so each file is sent once."""
from __future__ import annotations

import json
import mimetypes
import time
from pathlib import Path

from mlg.config import CACHE
from mlg.muse.http import MetaHTTP
from mlg.muse.media import sha256_file

INDEX = CACHE / "uploaded_files.json"
WEEK = 7 * 24 * 3600


def _index() -> dict[str, dict]:
    return json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {}


def upload(path: Path, http: MetaHTTP | None = None, expires_seconds: int = WEEK) -> str:
    digest = sha256_file(path)
    idx = _index()
    hit = idx.get(digest)
    if hit and hit["expires"] > time.time() + 3600:
        return hit["id"]
    http = http or MetaHTTP()
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with path.open("rb") as f:
        reply = http.request("POST", "/files",
                             data={"purpose": "user_data",
                                   "expires_after[anchor]": "created_at",
                                   "expires_after[seconds]": str(expires_seconds)},
                             files={"file": (path.name, f, mime)})
    file_id = reply.body["id"]
    idx[digest] = {"id": file_id, "expires": time.time() + expires_seconds}
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(idx, indent=1), encoding="utf-8")
    return file_id
