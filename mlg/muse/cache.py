"""Disk cache for model replies, keyed by sha256 of the full request.

Re-running the pipeline over the same media costs nothing; change the prompt
or the model and the key changes with it.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from mlg.config import CACHE

DIR = CACHE / "replies"


def key_for(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _path(key: str) -> Path:
    return DIR / key[:2] / f"{key}.json"


def get(key: str) -> Any | None:
    p = _path(key)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def put(key: str, value: Any) -> None:
    p = _path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
