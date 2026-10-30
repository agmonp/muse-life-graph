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


MAX_REFS = 6


def confirm_face(obs_id: str, person_id: str | None = None, new_name: str | None = None) -> str:
    """The owner says who a face is (from "Who is this?" or a question in the Edit Room).

    Links the face in the graph, records the answer, and keeps the crop as another
    reference photo of that person. Returns the person id."""
    from mlg import people
    from mlg.graph.db import session
    from mlg.perceive.crops import person_crop
    with session() as s:
        o = s.run("""MATCH (o:Observation {id: $id})-[:IN]->(mi:MediaItem)
                     RETURN o.bbox AS bbox, o.frame AS frame, mi.path AS path, mi.kind AS kind""", id=obs_id).single()
    if not o:
        raise KeyError(obs_id)
    from mlg import site
    crop = person_crop(site.local(o["path"]), o["kind"], o["bbox"], o["frame"])
    added_ref = None
    if new_name:
        if crop is None:
            raise ValueError("face too small to start a new person")
        person_id = people.new_person(new_name.strip(), crop, people.dataset_of(o["path"]))
    elif not person_id:
        raise ValueError("person_id or new_name required")
    else:
        ref = next((p for p in people.roster() if p["id"] == person_id), None)
        if crop is not None and ref and len(ref["crops"]) < MAX_REFS:
            added_ref = people.add_ref(person_id, crop)
    with session() as s:
        s.run("""MATCH (o:Observation {id: $oid}), (p:Person {id: $pid})
                 SET o.user_action = 'confirm'
                 MERGE (p)-[r:OBSERVED_AS]->(o) SET r.confidence = 1.0, r.confirmed_by = 'user',
                       r.rationale = 'confirmed by the owner'""", oid=obs_id, pid=person_id).consume()
    record(obs_id, "confirm", person_id, added_ref)
    return person_id


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
