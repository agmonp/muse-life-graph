"""Web app. For now: the "Who is this?" screen, where the owner settles identities.

    .venv\\Scripts\\python.exe -m uvicorn mlg.web.app:app --port 8800

Every answer is stored in the identity table (survives re-runs), applied to the
graph at once, and a confirmed face becomes another reference photo for that
person - so the next re-check recognises them better.
"""
from __future__ import annotations

import hashlib
import io
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from mlg import identity, people
from mlg.config import CACHE
from mlg.graph.db import session
from mlg.ingest.scan import connect
from mlg.muse.media import open_image
from mlg.perceive.crops import person_crop
from mlg.perceive.verify import MIN_CONF, check, identify

STATIC = Path(__file__).parent / "static"
CROP_CACHE = CACHE / "crops"
MAX_REFS = 6
app = FastAPI(title="Muse Life Graph")


def _jpeg(img, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _obs(oid: str) -> dict:
    with session() as s:
        r = s.run("""MATCH (o:Observation {id: $id})-[:IN]->(mi:MediaItem)
                     RETURN o.bbox AS bbox, o.frame AS frame, mi.path AS path, mi.kind AS kind, mi.id AS sha""",
                  id=oid).single()
    if not r:
        raise HTTPException(404, "observation not found")
    return dict(r)


def _crop_for(oid: str):
    o = _obs(oid)
    return person_crop(o["path"], o["kind"], o["bbox"], o["frame"])


@app.get("/")
def index():
    return FileResponse(STATIC / "who.html")


@app.get("/api/people")
def api_people(dataset: str = "real"):
    return [{"id": p["id"], "name": p["name"], "relation": p.get("relation"), "seen": p["seen"],
             "refs": len(p["crops"])} for p in people.roster(dataset)]


@app.get("/api/ref/{pid}")
def api_ref(pid: str, i: int = 0):
    for p in people.roster():
        if p["id"] == pid and p["crops"]:
            return FileResponse(p["crops"][min(i, len(p["crops"]) - 1)])
    raise HTTPException(404)


@app.get("/api/crop/{oid}")
def api_crop(oid: str):
    out = CROP_CACHE / (hashlib.sha1(oid.encode()).hexdigest() + ".jpg")
    if not out.exists():
        crop = _crop_for(oid)
        if crop is None:
            raise HTTPException(404, "face too small")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(_jpeg(crop))
    return FileResponse(out, headers={"Cache-Control": "max-age=86400"})


@app.get("/api/photo/{sha}")
def api_photo(sha: str):
    out = CROP_CACHE / f"photo_{sha[:24]}.jpg"
    if not out.exists():
        with session() as s:
            r = s.run("MATCH (mi:MediaItem {id: $id}) RETURN mi.path AS path, mi.kind AS kind", id=sha).single()
        if not r:
            raise HTTPException(404)
        if r["kind"] == "video":
            from mlg.perceive.keyframes import keyframes
            frames = keyframes(Path(r["path"]))
            img = open_image(frames[len(frames) // 2][1])
        else:
            img = open_image(Path(r["path"]))
        img.thumbnail((900, 900))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(_jpeg(img, 80))
    return FileResponse(out, headers={"Cache-Control": "max-age=86400"})


def _queue(dataset: str) -> list[dict]:
    done = identity.answered()
    with session() as s:
        rows = s.run("""MATCH (o:Observation)-[:IN]->(mi:MediaItem)
                        WHERE o.bbox IS NOT NULL AND o.user_action IS NULL AND NOT (o)<-[:OBSERVED_AS]-(:Person)
                        OPTIONAL MATCH (m:Moment)-[:DEPICTED_IN]->(mi)
                        OPTIONAL MATCH (cand:Person {id: o.candidate})
                        RETURN o.id AS id, o.bbox AS bbox, o.appearance AS appearance, o.role AS role,
                               o.confidence AS conf, o.candidate AS cand, cand.name AS cand_name,
                               o.candidate_verdict AS verdict, o.candidate_conf AS vconf,
                               o.candidate_reason AS vreason, mi.id AS sha, mi.path AS path, mi.kind AS kind,
                               m.start AS date, m.summary AS summary, m.event_title AS event""").data()
    con = connect()
    has_ctx = bool(con.execute("SELECT 1 FROM sqlite_master WHERE name='context'").fetchone())
    out = []
    for r in rows:
        if r["id"] in done or people.dataset_of(r["path"]) != dataset:
            continue
        x1, y1, x2, y2 = (r["bbox"] + [0, 0, 0, 0])[:4]
        r["area"] = abs((x2 - x1) * (y2 - y1)) / 1e6
        if has_ctx:
            c = con.execute("SELECT album FROM context WHERE path=?", (r["path"],)).fetchone()
            r["album"] = c["album"] if c else None
        r.pop("path")
        out.append(r)
    # proposed matches first, then unknown faces; within each, the biggest (clearest) faces on top
    out.sort(key=lambda r: (r["cand"] is None, r["area"] < 0.004, r["verdict"] != "same", -r["area"]))
    return out


@app.get("/api/faces")
def api_faces(dataset: str = "real", limit: int = 40):
    q = _queue(dataset)
    return {"total": len(q), "faces": q[:limit]}


class Answer(BaseModel):
    obs_id: str
    action: str                 # confirm | skip | not_person
    person_id: str | None = None
    new_name: str | None = None


@app.post("/api/answer")
def api_answer(a: Answer):
    o = _obs(a.obs_id)
    pid = a.person_id
    added_ref = None
    if a.action == "confirm":
        crop = _crop_for(a.obs_id)
        if a.new_name:
            if crop is None:
                raise HTTPException(400, "face too small to start a new person")
            pid = people.new_person(a.new_name.strip(), crop, people.dataset_of(o["path"]))
        elif not pid:
            raise HTTPException(400, "person_id or new_name required")
        else:
            ref = next((p for p in people.roster() if p["id"] == pid), None)
            if crop is not None and ref and len(ref["crops"]) < MAX_REFS:
                added_ref = people.add_ref(pid, crop)
        with session() as s:
            s.run("""MATCH (o:Observation {id: $oid}), (p:Person {id: $pid})
                     SET o.user_action = 'confirm'
                     MERGE (p)-[r:OBSERVED_AS]->(o) SET r.confidence = 1.0, r.confirmed_by = 'user',
                           r.rationale = 'confirmed by the owner'""", oid=a.obs_id, pid=pid).consume()
    elif a.action in ("skip", "not_person"):
        with session() as s:
            s.run("MATCH (o:Observation {id: $oid}) SET o.user_action = $a", oid=a.obs_id, a=a.action).consume()
    else:
        raise HTTPException(400, "unknown action")
    identity.record(a.obs_id, a.action, pid, added_ref)
    return {"ok": True, "person_id": pid}


class Undo(BaseModel):
    obs_id: str


@app.post("/api/undo")
def api_undo(u: Undo):
    row = identity.undo(u.obs_id)
    if row and row.get("ref") and row.get("person_id"):
        people.remove_ref(row["person_id"], row["ref"])
    with session() as s:
        s.run("""MATCH (o:Observation {id: $oid}) SET o.user_action = null
                 WITH o OPTIONAL MATCH (:Person)-[r:OBSERVED_AS {confirmed_by: 'user'}]->(o) DELETE r""",
              oid=u.obs_id).consume()
    return {"ok": True}


RECHECK = {"running": False, "done": 0, "total": 0, "matched": 0, "proposed": 0, "started": 0.0}


def _recheck(dataset: str) -> None:
    roster = people.roster(dataset)
    by_id = {p["id"]: p for p in roster}
    queue = [f for f in _queue(dataset) if f["area"] >= 0.004]
    RECHECK.update(running=True, done=0, total=len(queue), matched=0, proposed=0, started=time.time())
    try:
        for f in queue:
            crop = _crop_for(f["id"])
            guess = {"person_id": f["cand"]} if f["cand"] else identify(crop, roster)
            pid = guess.get("person_id")
            if pid in by_id:
                v = check(by_id[pid], crop)
                conf = float(v.get("confidence") or 0)
                with session() as s:
                    if v.get("verdict") == "same" and conf >= MIN_CONF:
                        s.run("""MATCH (o:Observation {id: $oid}), (p:Person {id: $pid})
                                 MERGE (p)-[r:OBSERVED_AS]->(o)
                                 SET r.confidence = $c, r.rationale = $why, r.confirmed_by = 'two-key'""",
                              oid=f["id"], pid=pid, c=conf, why=v.get("reason", "")).consume()
                        identity.record(f["id"], "auto", pid)
                        RECHECK["matched"] += 1
                    else:
                        s.run("""MATCH (o:Observation {id: $oid})
                                 SET o.candidate = $pid, o.candidate_verdict = $v, o.candidate_conf = $c,
                                     o.candidate_reason = $why""",
                              oid=f["id"], pid=pid, v=v.get("verdict"), c=conf, why=v.get("reason", "")).consume()
                        RECHECK["proposed"] += 1
            RECHECK["done"] += 1
    finally:
        RECHECK["running"] = False


@app.post("/api/recheck")
def api_recheck(dataset: str = "real"):
    if not RECHECK["running"]:
        threading.Thread(target=_recheck, args=(dataset,), daemon=True).start()
        time.sleep(0.2)
    return RECHECK


@app.get("/api/recheck")
def api_recheck_status():
    return RECHECK
