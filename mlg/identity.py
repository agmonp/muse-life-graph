"""The human's answers to "who is this?", kept outside the graph so re-runs never lose them.

Re-perceiving an item rebuilds its sub-graph from scratch; answers recorded here
are applied again on every run (keyed by observation id "<sha>:<local id>").
"""
from __future__ import annotations

import time

from mlg.ingest.scan import connect

ACTIONS = {"confirm", "skip", "not_person", "auto"}  # auto = two-key machine match after a re-check

SCHEMA = """CREATE TABLE IF NOT EXISTS identity (
  obs_id TEXT PRIMARY KEY, sha TEXT NOT NULL, action TEXT NOT NULL, person_id TEXT, at REAL)"""


def _con():
    con = connect()
    con.execute(SCHEMA)
    if "ref" not in {r["name"] for r in con.execute("PRAGMA table_info(identity)")}:
        con.execute("ALTER TABLE identity ADD COLUMN ref TEXT")  # reference crop this answer added
    return con


def record(obs_id: str, action: str, person_id: str | None = None, ref: str | None = None) -> None:
    if action not in ACTIONS:
        raise ValueError(action)
    con = _con()
    con.execute("INSERT OR REPLACE INTO identity (obs_id, sha, action, person_id, at, ref) VALUES (?,?,?,?,?,?)",
                (obs_id, obs_id.split(":")[0], action, person_id, time.time(), ref))
    con.commit()


def undo(obs_id: str) -> dict | None:
    """Forget an answer; returns it so the caller can roll back what it changed."""
    con = _con()
    row = con.execute("SELECT * FROM identity WHERE obs_id=?", (obs_id,)).fetchone()
    con.execute("DELETE FROM identity WHERE obs_id=?", (obs_id,))
    con.commit()
    return dict(row) if row else None


def for_item(sha: str) -> dict[str, dict]:
    """local id -> answer row for one media item."""
    rows = _con().execute("SELECT * FROM identity WHERE sha=?", (sha,)).fetchall()
    return {r["obs_id"].split(":", 1)[1]: dict(r) for r in rows}


def answered() -> set[str]:
    return {r["obs_id"] for r in _con().execute("SELECT obs_id FROM identity")}
