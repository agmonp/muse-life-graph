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

from mlg import identity, people, site
from mlg.config import CACHE
from mlg.graph.db import session
from mlg.ingest.scan import connect
from mlg.muse.media import open_image
from mlg.perceive.crops import person_crop
from mlg.perceive.verify import MIN_CONF, check, identify

STATIC = Path(__file__).parent / "static"
CROP_CACHE = CACHE / "crops"
app = FastAPI(title="Muse Life Graph")
VOICE_TILE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 150 100"><rect width="150" height="100" '
              'fill="#e8e4f6"/><g fill="none" stroke="#5f3dc4" stroke-width="5" stroke-linecap="round">'
              '<path d="M45 50v0M60 38v24M75 28v44M90 38v24M105 50v0"/></g>'
              '<text x="75" y="92" font-family="sans-serif" font-size="11" fill="#5f3dc4" '
              'text-anchor="middle">voice</text></svg>')


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
    return {**dict(r), "path": site.local(r["path"])}


def _crop_for(oid: str):
    o = _obs(oid)
    return person_crop(o["path"], o["kind"], o["bbox"], o["frame"])


APP = STATIC / "app"

# ---------------- the hosted site: an access code, and nobody changes who is who ----------------

from fastapi import Request  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse  # noqa: E402

READ_ONLY = ("/api/answer", "/api/answer_group", "/api/undo", "/api/recheck", "/api/import", "/api/titles")
OPEN = ("/bless/", "/api/bless/", "/app/logo.svg", "/enter")
CODE_PAGE = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Muse Life Graph</title><link rel="icon" href="/app/logo.svg">
<body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#f6f1ea;font:16px system-ui;color:#1e1916">
<form method="post" action="/enter" style="background:#fffdfa;padding:32px;border-radius:20px;box-shadow:0 8px 30px #0001;width:min(360px,90vw)">
<img src="/app/logo.svg" width="44" alt=""><h1 style="font:600 26px Georgia,serif;margin:14px 0 6px">Muse Life Graph</h1>
<p style="color:#5f564f;margin:0 0 18px">A private demo of one family's life graph. Enter the access code from the submission.</p>
<input name="code" type="password" autofocus placeholder="Access code" style="width:100%;box-sizing:border-box;padding:12px 14px;border:1px solid #d8ccbf;border-radius:12px;font:inherit">
<button style="margin-top:12px;width:100%;padding:12px;border:0;border-radius:999px;background:#d9542a;color:#fff;font:600 16px system-ui">Enter</button>
{msg}</form></body></html>"""


@app.middleware("http")
async def site_guard(request: Request, call_next):
    path = request.url.path
    if site.enabled():
        if site.CODE and request.cookies.get("mlg_code") != site.CODE and not path.startswith(OPEN):
            if path.startswith("/api/"):
                return JSONResponse({"detail": "access code needed"}, status_code=401)
            return HTMLResponse(CODE_PAGE.replace("{msg}", ""))
        if request.method == "POST" and path.startswith(READ_ONLY):
            return JSONResponse({"detail": "This is a demo of someone's real family: names can't be changed here. "
                                           "Run Muse Life Graph on your own photos to name your people."},
                                status_code=403)
    return await call_next(request)


@app.post("/enter")
async def enter(request: Request):
    form = await request.form()
    import hmac
    if site.CODE and hmac.compare_digest(str(form.get("code") or ""), site.CODE):
        r = RedirectResponse("/", status_code=303)
        r.set_cookie("mlg_code", site.CODE, max_age=60 * 60 * 24 * 30, httponly=True, samesite="lax", secure=True)
        return r
    return HTMLResponse(CODE_PAGE.replace("{msg}", '<p style="color:#c92a2a">That code is not right.</p>'), status_code=401)


@app.get("/")
def index():
    return FileResponse(APP / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/app/{name}")
def app_file(name: str):
    f = (APP / name).resolve()
    if f.parent != APP.resolve() or not f.exists():
        raise HTTPException(404)
    return FileResponse(f, headers={"Cache-Control": "no-cache"})


@app.get("/studio")
def studio_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/#/films")


# ---------------- library: the screens ----------------

from mlg import imports, library, search  # noqa: E402


def _or404(x):
    if x is None:
        raise HTTPException(404)
    return x


@app.get("/api/overview")
def api_overview():
    return library.overview()


@app.get("/api/memories")
def api_memories():
    return library.memories()


@app.get("/api/memory/{key:path}")
def api_memory(key: str):
    return _or404(library.memory(key))


@app.get("/api/timeline")
def api_timeline():
    return library.timeline()


@app.get("/api/year/{y}")
def api_year(y: str):
    return library.year(y)


@app.get("/api/persons")
def api_persons():
    return library.people_list()


@app.get("/api/person/{pid}")
def api_person(pid: str):
    return _or404(library.person(pid))


@app.get("/api/graph")
def api_graph():
    return library.graph()


@app.get("/api/shared")
def api_shared(a: str, b: str):
    return library.shared(a, b)


@app.get("/api/moment/{mid}")
def api_moment(mid: str):
    return _or404(library.moment(mid))


@app.get("/api/media/{sha}")
def api_media(sha: str):
    """The original file, for full-size viewing and video playback."""
    with session() as s:
        r = s.run("MATCH (mi:MediaItem {id: $id}) RETURN mi.path AS path, mi.kind AS kind", id=sha).single()
    if r:
        r = {**dict(r), "path": site.local(r["path"])}
    if not r or not Path(r["path"]).exists():
        raise HTTPException(404)
    if r["kind"] == "photo" and Path(r["path"]).suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        return api_photo(sha)   # HEIC and friends: the browser gets the JPEG preview
    return FileResponse(r["path"])


@app.get("/api/search")
def api_search(q: str):
    if not q.strip():
        raise HTTPException(400, "empty search")
    return search.search(q.strip())


@app.get("/api/ask")
def api_ask(q: str):
    if not q.strip():
        raise HTTPException(400, "empty question")
    return search.ask(q.strip())


@app.post("/api/titles")
def api_titles():
    def run():
        try:
            library.write_titles()
        except Exception:  # noqa: BLE001 - titles are a nicety; the cards fall back to Muse's event names
            pass
    threading.Thread(target=run, daemon=True).start()
    return {"ok": True}


# ---------------- import ----------------

class FolderImport(BaseModel):
    path: str | None = None      # None = open the folder picker on this computer


class MetaImport(BaseModel):
    paths: list[str] | None = None


@app.get("/api/import")
def api_import_status():
    return {**imports.status(), "waiting": imports.estimate()}


@app.post("/api/import/folder")
def api_import_folder(r: FolderImport):
    path = r.path or next(iter(imports.pick("folder")), None)
    if not path:
        return {"cancelled": True}
    try:
        return imports.start_folder(path)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/import/meta")
def api_import_meta(r: MetaImport):
    paths = r.paths or imports.pick("zip")
    if not paths:
        return {"cancelled": True}
    try:
        return imports.start_meta(paths)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/import/look")
def api_import_look(limit: int | None = None):
    try:
        return imports.start_looking(limit)
    except RuntimeError as e:
        raise HTTPException(400, str(e))


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
        r = {**dict(r), "path": site.local(r["path"])}
        if r["kind"] == "audio":   # a voice recording (a blessing) has no picture: show a voice tile
            return Response(VOICE_TILE, media_type="image/svg+xml", headers={"Cache-Control": "max-age=86400"})
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
def api_faces(dataset: str = "real", limit: int = 40, unclear: bool = False):
    q = _queue(dataset)
    if unclear:   # only the faces the fingerprint model could not read (profile, sunglasses, tiny, blurred)
        from mlg import faces
        con = faces._con()
        ids = [f["id"] for f in q]
        bad = {k for k, v in con.execute(f"SELECT key, v FROM vec WHERE key IN ({','.join('?' * len(ids))})", ids)
               if v is None} if ids else set()
        q = [f for f in q if f["id"] in bad]
    return {"total": len(q), "faces": q[:limit]}


@app.get("/api/face_groups")
def api_face_groups(limit: int = 30, per: int = 24):
    from mlg import faces
    g = faces.groups()
    if g["waiting"] and not faces.JOB["running"]:
        threading.Thread(target=faces.index, daemon=True).start()
    people = {p["id"]: p for p in library.people_list()}
    return {**g, "total_groups": len(g["groups"]),
            "groups": [{**x, "faces": x["faces"][:per]} for x in g["groups"][:limit]],
            "people": sorted(people.values(), key=lambda p: (-p["count"], p["name"]))}


class GroupAnswer(BaseModel):
    obs_ids: list[str]
    action: str                 # confirm | skip | not_person
    person_id: str | None = None
    new_name: str | None = None


@app.post("/api/answer_group")
def api_answer_group(a: GroupAnswer):
    """One answer for a whole group of faces: the first one creates the person if needed."""
    if not a.obs_ids:
        raise HTTPException(400, "no faces chosen")
    pid, done = a.person_id, []
    for oid in a.obs_ids:
        try:
            if a.action == "confirm":
                pid = identity.confirm_face(oid, pid, None if pid else a.new_name)
            elif a.action in ("skip", "not_person"):
                with session() as s:
                    s.run("MATCH (o:Observation {id: $oid}) SET o.user_action = $a", oid=oid, a=a.action).consume()
                identity.record(oid, a.action, pid)
            else:
                raise HTTPException(400, "unknown action")
            done.append(oid)
        except ValueError:
            continue   # a face that cannot be cropped any more; the rest still count
    library.invalidate()
    return {"ok": True, "person_id": pid, "done": done}


class Answer(BaseModel):
    obs_id: str
    action: str                 # confirm | skip | not_person
    person_id: str | None = None
    new_name: str | None = None


@app.post("/api/answer")
def api_answer(a: Answer):
    _obs(a.obs_id)
    pid = a.person_id
    if a.action == "confirm":
        try:
            pid = identity.confirm_face(a.obs_id, pid, a.new_name)
        except ValueError as e:
            raise HTTPException(400, str(e))
    elif a.action in ("skip", "not_person"):
        with session() as s:
            s.run("MATCH (o:Observation {id: $oid}) SET o.user_action = $a", oid=a.obs_id, a=a.action).consume()
        identity.record(a.obs_id, a.action, pid)
    else:
        raise HTTPException(400, "unknown action")
    library.invalidate()
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
    library.invalidate()
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


# ---------------- Blessings (Shema) ----------------

from fastapi import File, Form, UploadFile  # noqa: E402

from mlg.shema import blessings  # noqa: E402


class BlessingRequest(BaseModel):
    person_id: str
    dataset: str = "real"
    message: str = ""


@app.post("/api/blessing_requests")
def api_new_blessing_request(r: BlessingRequest):
    token = blessings.create_request(r.person_id, r.dataset, r.message.strip())
    return {"token": token, "url": f"/bless/{token}"}


@app.get("/api/blessing_requests")
def api_blessing_requests():
    out = blessings.list_requests()
    names = {p["id"]: p["name"] for p in people.roster()}
    for r in out:
        r["name"] = names.get(r["person_id"], r["person_id"])
        for it in r["items"]:
            it.pop("path", None)
    return out


@app.get("/bless/{token}")
def bless_page(token: str):
    return FileResponse(STATIC / "bless.html")


@app.get("/api/bless/{token}")
def api_bless_info(token: str):
    info = blessings.request_info(token)
    if not info or not info["open"]:
        raise HTTPException(404, "this link is not active")
    return {"name": info["name"], "relation": info["relation"], "message": info["message"]}


@app.get("/api/bless/{token}/photo")
def api_bless_photo(token: str):
    info = blessings.request_info(token)
    if not info or not info.get("crop"):
        raise HTTPException(404)
    return FileResponse(info["crop"])


def _process_later(item_id: int) -> None:
    def run():
        try:
            blessings.process(item_id)
        except Exception:  # noqa: BLE001 - status 'failed' is shown on the owner's panel
            pass
    threading.Thread(target=run, daemon=True).start()


@app.post("/api/bless/{token}")
async def api_bless_submit(token: str, from_name: str = Form(...), relation: str = Form(""),
                           consent_film: bool = Form(True), audio: UploadFile | None = File(None),
                           photos: list[UploadFile] = File(default=[])):
    if not from_name.strip():
        raise HTTPException(400, "please write your name")
    saved = []
    try:
        if audio is not None:
            data = await audio.read()
            if len(data) > 25 * 1024 * 1024:
                raise HTTPException(413, "recording too long")
            if data:
                saved.append(blessings.save(token, from_name.strip(), relation.strip(), consent_film,
                                            audio.filename or "blessing.webm", data, "audio"))
        for ph in photos[:10]:
            data = await ph.read()
            if data:
                kind = "video" if (ph.content_type or "").startswith("video") else "photo"
                saved.append(blessings.save(token, from_name.strip(), relation.strip(), consent_film,
                                            ph.filename or "photo.jpg", data, kind))
    except ValueError as e:
        raise HTTPException(404, str(e))
    for item_id in saved:
        _process_later(item_id)
    return {"ok": True, "received": len(saved)}


# ---------------- Studio / Edit Room ----------------

from mlg.studio.make import FILMS, make  # noqa: E402

FILM_THREADS: dict[str, threading.Thread] = {}


class FilmRequest(BaseModel):
    request: str
    dataset: str = "real"
    template: str | None = None      # None = the producer picks from the request
    ask: bool = True                 # pause and ask the owner before cutting


ASK_WAIT = 600   # seconds; after that the crew goes with its own picks


@app.get("/api/templates")
def api_templates():
    from mlg.studio.templates import catalog
    return catalog()


@app.post("/api/films")
def api_make_film(r: FilmRequest):
    if not r.request.strip():
        raise HTTPException(400, "empty request")
    film_id = time.strftime("film_%Y%m%d_%H%M%S")

    def run():
        try:
            make(r.request.strip(), r.dataset, film_id, template=r.template or None,
                 ask_wait=ASK_WAIT if r.ask else 0)
        except Exception:  # noqa: BLE001 - the error is in state.json for the page
            pass

    th = threading.Thread(target=run, daemon=True)
    FILM_THREADS[film_id] = th
    th.start()
    for _ in range(50):   # wait until state.json exists so the page can poll it
        if (FILMS / film_id / "state.json").exists():
            break
        time.sleep(0.1)
    return {"id": film_id}


def _state(film_id: str) -> dict:
    import json
    p = FILMS / film_id / "state.json"
    if not p.exists():
        raise HTTPException(404, "no such film")
    st = json.loads(p.read_text(encoding="utf-8"))
    if st.get("status") in ("running", "waiting") and film_id not in FILM_THREADS:
        st["status"] = "interrupted"   # the server restarted while this film was being made
    return st


class Answers(BaseModel):
    answers: dict[str, str]


@app.post("/api/films/{film_id}/answers")
def api_film_answers(film_id: str, a: Answers):
    import json
    st = _state(film_id)
    if st.get("status") != "waiting":
        raise HTTPException(409, "the crew is not waiting for answers")
    p = FILMS / film_id / "answers.json"
    old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    old.update(a.answers)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    return {"ok": True, "answered": len(old)}


@app.get("/api/films")
def api_films():
    out = []
    for d in sorted(FILMS.glob("film_*"), reverse=True):
        try:
            st = _state(d.name)
        except HTTPException:
            continue
        v = st.get("versions", {})
        first = next((m for sc in st.get("scenes") or [] for m in sc.get("moments") or []), None)
        out.append({"id": st["id"], "title": st.get("title") or st["request"][:60], "status": st["status"],
                    "cover": first.split(":")[0] if first else None,
                    "request": st["request"], "v1": v.get("v1", {}).get("score"), "v2": v.get("v2", {}).get("score")})
    return out


@app.get("/api/films/{film_id}")
def api_film(film_id: str):
    st = _state(film_id)
    for v in st.get("versions", {}).values():
        v.pop("path", None)
    return st


@app.get("/api/films/{film_id}/video/{version}")
def api_film_video(film_id: str, version: str):
    if version not in ("v1", "v2"):
        raise HTTPException(404)
    p = FILMS / film_id / version / "film.mp4"
    if not p.exists():
        raise HTTPException(404, "not rendered yet")
    return FileResponse(p, media_type="video/mp4")
