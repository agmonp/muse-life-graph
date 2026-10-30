"""Face fingerprints: group the faces Muse found, so one answer names many.

Muse finds the people in a picture and where they are; this module turns each
face into a 128-number fingerprint (OpenCV YuNet finds and aligns the face
inside Muse's box, SFace describes it) and stores it once per observation.

    groups()   unnamed faces that look like the same person, biggest group first,
               each with a suggested name when it matches someone already named
    index()    fingerprints for every face that has none yet (a background job)

Thresholds are cosine similarities on SFace vectors (OpenCV calls >= 0.363 the same
person); grouping uses a stricter bar than suggesting, so groups stay clean and a
wrong suggestion is one click to refuse.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import numpy as np

from mlg.config import CACHE, DATA
from mlg.graph.db import session

MODELS = DATA / "models"
DETECTOR = MODELS / "face_detection_yunet_2023mar.onnx"
RECOGNIZER = MODELS / "face_recognition_sface_2021dec.onnx"
DB = CACHE / "faces.sqlite"
SAME_GROUP = 0.45      # two faces join one group
SUGGEST = 0.40         # a group gets a person's name as a suggestion
STRONG = 0.55          # the suggestion is shown as "very likely"
_LOCK = threading.Lock()
_NETS: dict = {}
JOB: dict = {"running": False, "done": 0, "total": 0}


def _con() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB, check_same_thread=False)
    con.execute("CREATE TABLE IF NOT EXISTS vec (key TEXT PRIMARY KEY, v BLOB, score REAL, at REAL)")
    return con


MODEL_URL = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"


def _ensure_models() -> None:
    """First run: fetch the two OpenCV model files (YuNet MIT, SFace Apache-2.0) from opencv_zoo."""
    import urllib.request
    for f, sub in ((DETECTOR, "face_detection_yunet"), (RECOGNIZER, "face_recognition_sface")):
        if not f.exists():
            f.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(f"{MODEL_URL}{sub}/{f.name}", f)


def _nets():
    import cv2
    if not _NETS:
        _ensure_models()
        _NETS["det"] = cv2.FaceDetectorYN.create(str(DETECTOR), "", (320, 320), 0.6, 0.3, 50)
        _NETS["rec"] = cv2.FaceRecognizerSF.create(str(RECOGNIZER), "")
    return _NETS["det"], _NETS["rec"]


def embed(img) -> tuple[np.ndarray, float] | None:
    """PIL image of one person's head -> (unit vector, detector score), or None when no face is found."""
    import cv2
    rgb = np.asarray(img.convert("RGB"))
    h, w = rgb.shape[:2]
    if min(h, w) < 160:   # small faces: the detector needs some pixels
        k = 160 / min(h, w)
        rgb = cv2.resize(rgb, (int(w * k), int(h * k)), interpolation=cv2.INTER_CUBIC)
        h, w = rgb.shape[:2]
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    with _LOCK:
        det, rec = _nets()
        det.setInputSize((w, h))
        _, found = det.detect(bgr)
        if found is None or not len(found):
            return None
        # the face Muse meant is the big one near the middle of its box
        cx, cy = w / 2, h / 2
        best = max(found, key=lambda f: f[14] * (f[2] * f[3]) / (1 + ((f[0] + f[2] / 2 - cx) ** 2 + (f[1] + f[3] / 2 - cy) ** 2) / (w * h)))
        # Muse's box holds two people of similar size: which face it meant is a guess, so give no fingerprint
        if sum(1 for f in found if f[14] >= 0.7 and f[2] * f[3] >= 0.5 * best[2] * best[3]) > 1:
            return None
        aligned = rec.alignCrop(bgr, best)
        v = rec.feature(aligned).flatten().astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-9), float(best[14])


def _store(con, key: str, res) -> None:
    con.execute("INSERT OR REPLACE INTO vec VALUES (?,?,?,?)",
                (key, res[0].tobytes() if res else None, res[1] if res else None, time.time()))


def _vectors(con, keys: list[str]) -> dict[str, np.ndarray]:
    out = {}
    for i in range(0, len(keys), 900):
        part = keys[i:i + 900]
        for k, v in con.execute(f"SELECT key, v FROM vec WHERE key IN ({','.join('?' * len(part))})", part):
            if v:
                out[k] = np.frombuffer(v, dtype=np.float32)
    return out


def _observations() -> list[dict]:
    with session() as s:
        return s.run("""MATCH (o:Observation)-[:IN]->(mi:MediaItem) WHERE o.bbox IS NOT NULL
                        OPTIONAL MATCH (p:Person)-[:OBSERVED_AS]->(o)
                        OPTIONAL MATCH (m:Moment)-[:DEPICTED_IN]->(mi)
                        RETURN o.id AS id, o.bbox AS bbox, o.frame AS frame, o.user_action AS action,
                               mi.id AS sha, mi.path AS path, mi.kind AS kind, m.start AS date,
                               collect(p.id)[0] AS person""").data()


def _all_refs() -> dict[str, list[str]]:
    """Reference crops of every named person (the roster for Muse's prompt is capped; this is not)."""
    with session() as s:
        rows = s.run("""MATCH (p:Person {confirmed: true})
                        RETURN p.id AS id, [c IN [p.ref_crop] + coalesce(p.ref_crops, []) WHERE c IS NOT NULL] AS crops""").data()
    return {r["id"]: [c for c in r["crops"] if Path(c).exists()] for r in rows}


def index() -> dict:
    """Fingerprint every face (and every reference crop) that has none yet."""
    from mlg.perceive.crops import person_crop
    from mlg.muse.media import open_image
    if JOB["running"]:
        return JOB
    JOB.update(running=True, done=0, total=0, started=time.time())
    try:
        con = _con()
        have = {k for (k,) in con.execute("SELECT key FROM vec")}
        obs = [o for o in _observations() if o["id"] not in have and o["kind"] in ("photo", "video")]
        refs = [c for cs in _all_refs().values() for c in cs if f"ref:{c}" not in have]
        JOB["total"] = len(obs) + len(refs)
        for c in refs:
            try:
                _store(con, f"ref:{c}", embed(open_image(Path(c))))
            except Exception:  # noqa: BLE001 - an unreadable crop is just skipped
                _store(con, f"ref:{c}", None)
            JOB["done"] += 1
        for n, o in enumerate(obs, 1):
            try:
                crop = person_crop(o["path"], o["kind"], o["bbox"], o["frame"], max_side=640)
                _store(con, o["id"], embed(crop) if crop is not None else None)
            except Exception:  # noqa: BLE001 - one bad file must not stop the rest
                _store(con, o["id"], None)
            JOB["done"] += 1
            if n % 50 == 0:
                con.commit()
        con.commit()
    finally:
        JOB["running"] = False
    return JOB


def _people_vectors(con, obs: list[dict]) -> dict[str, np.ndarray]:
    """Every fingerprint we have per named person: their linked faces and their reference crops."""
    per: dict[str, list[np.ndarray]] = {}
    linked = [o for o in obs if o["person"]]
    vecs = _vectors(con, [o["id"] for o in linked])
    for o in linked:
        if o["id"] in vecs:
            per.setdefault(o["person"], []).append(vecs[o["id"]])
    for pid, crops in _all_refs().items():
        rv = _vectors(con, [f"ref:{c}" for c in crops])
        per.setdefault(pid, []).extend(rv.values())
    return {pid: np.stack(v) for pid, v in per.items() if v}


def _best_person(v: np.ndarray, people: dict[str, np.ndarray]) -> tuple[str | None, float]:
    best, sim = None, -1.0
    for pid, mat in people.items():
        s = mat @ v
        score = float(np.mean(np.sort(s)[-3:]))   # the 3 closest pictures of them, not one lucky match
        if score > sim:
            best, sim = pid, score
    return best, sim


def groups(skip: set[str] | None = None) -> dict:
    """Unnamed faces as groups of (probably) one person each, largest first; faces with no fingerprint last."""
    skip = skip or set()
    con = _con()
    obs = _observations()
    open_ = [o for o in obs if not o["person"] and not o["action"] and o["id"] not in skip]
    vecs = _vectors(con, [o["id"] for o in open_])
    known = {k for (k,) in con.execute("SELECT key FROM vec")}
    people = _people_vectors(con, obs)
    with_v = [o for o in open_ if o["id"] in vecs]
    # leader clustering: each face joins the closest group when it is close enough, else starts one
    cents: list[np.ndarray] = []
    members: list[list[dict]] = []
    for o in sorted(with_v, key=lambda o: o["id"]):
        v = vecs[o["id"]]
        if cents:
            sims = np.stack(cents) @ v
            k = int(np.argmax(sims))
            if sims[k] >= SAME_GROUP:
                members[k].append(o)
                c = cents[k] * (len(members[k]) - 1) + v
                cents[k] = c / (np.linalg.norm(c) + 1e-9)
                continue
        cents.append(v.copy())
        members.append([o])
    from mlg import library
    _, ppl = library.data()
    out = []
    for c, ms in zip(cents, members):
        pid, sim = _best_person(c, people) if people else (None, 0.0)
        ms.sort(key=lambda o: -float(c @ vecs[o["id"]]))   # most typical faces first
        out.append({"id": ms[0]["id"], "size": len(ms),
                    "faces": [{"id": o["id"], "sha": o["sha"], "date": (o["date"] or "")[:10],
                               "sim": round(float(c @ vecs[o["id"]]), 2)} for o in ms],
                    "photos": len({o["sha"] for o in ms}),
                    "suggest": {"id": pid, "name": ppl[pid]["name"], "sim": round(sim, 2), "strong": sim >= STRONG}
                    if pid in ppl and sim >= SUGGEST else None})
    # bigger groups first; a suggested group before an unknown one of the same size
    out.sort(key=lambda g: (-g["size"], g["suggest"] is None))
    loose = [o for o in open_ if o["id"] not in vecs]
    return {"groups": out, "no_fingerprint": len([o for o in loose if o["id"] in known]),
            "waiting": len([o for o in loose if o["id"] not in known]), "open": len(open_), "job": dict(JOB)}
