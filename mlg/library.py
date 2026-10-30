"""The owner's library: everything the app's screens read from the life graph.

One graph query loads every moment (with its people, feelings, words and place);
the screens are views over it: memories (moments that belong together), the
timeline, people and how they connect, and one moment in full. The load is
cached until the graph changes (new perceptions, a face named).
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import Counter, defaultdict
from datetime import date

from mlg import site
from mlg.config import CACHE
from mlg.graph.db import session
from mlg.ingest.scan import connect

_LOCK = threading.Lock()
_CACHE: dict = {"key": None, "at": 0.0, "moments": [], "people": {}}
TITLES = CACHE / "memory_titles.json"


def _version() -> tuple:
    with session() as s:
        r = s.run("""MATCH (m:Moment) WITH count(m) AS n
                     OPTIONAL MATCH (:Person)-[r:OBSERVED_AS]->() RETURN n, count(r) AS links""").single()
        p = s.run("MATCH (p:Person) RETURN count(p) AS c, collect(p.name) AS names").single()
    return r["n"], r["links"], p["c"], hashlib.md5("|".join(sorted(p["names"])).encode()).hexdigest()


def _albums() -> dict[str, str]:
    con = connect()
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='context'").fetchone():
        return {}
    return {r["path"]: r["album"] for r in con.execute("SELECT path, album FROM context") if r["album"]}


def _load() -> tuple[list[dict], dict]:
    with session() as s:
        rows = s.run("""
            MATCH (m:Moment)-[:DEPICTED_IN]->(mi:MediaItem)
            OPTIONAL MATCH (p:Person)-[r:OBSERVED_AS]->(o:Observation)-[:PRESENT_AT]->(m)
            WITH m, mi, collect(DISTINCT {id: p.id, name: p.name, obs: o.id, bbox: o.bbox,
                                         by: r.confirmed_by}) AS faces
            OPTIONAL MATCH (x:Observation)-[:PRESENT_AT]->(m)
            WHERE x.bbox IS NOT NULL AND NOT (:Person)-[:OBSERVED_AS]->(x)
                  AND coalesce(x.user_action, '') = ''
            WITH m, mi, faces, collect(DISTINCT {obs: x.id, bbox: x.bbox, cand: x.candidate}) AS unknown
            OPTIONAL MATCH (m)-[ev:EVOKED_EMOTION]->(e:Emotion)
            WITH m, mi, faces, unknown, collect(DISTINCT e.name) AS mood
            OPTIONAL MATCH (m)-[:OCCURRED_AT]->(l:Location)
            WITH m, mi, faces, unknown, mood, collect(DISTINCT l.name)[0] AS place
            OPTIONAL MATCH (u:Utterance)-[:IN]->(mi)
            WITH m, mi, faces, unknown, mood, place,
                 collect(DISTINCT {id: u.id, text: u.text, text_en: u.text_en, t0: u.t0, t1: u.t1}) AS said
            OPTIONAL MATCH (m)-[:FEATURES]->(ob:Object)
            WITH m, mi, faces, unknown, mood, place, said, collect(DISTINCT ob.name)[..8] AS objects
            OPTIONAL MATCH (m)-[:INCLUDES]->(a:Activity)
            RETURN m.id AS id, m.start AS date, m.date_source AS date_source, m.date_rationale AS date_why,
                   m.summary AS summary, m.event_type AS event_type, m.event_title AS event,
                   m.place_type AS place_type, m.open_questions AS questions,
                   mi.id AS sha, mi.path AS path, mi.kind AS kind, mi.duration_s AS duration,
                   mi.width AS width, mi.height AS height,
                   faces, unknown, mood, place, said, objects, collect(DISTINCT a.name)[..6] AS activities
            """).data()
        ppl = s.run("""MATCH (p:Person {confirmed: true})
                       RETURN p.id AS id, p.name AS name, p.relation AS relation, p.is_owner AS owner,
                              p.ref_crop AS crop, coalesce(p.groups, []) AS groups, p.name_en AS name_en""").data()
    albums = _albums()
    out = []
    for r in rows:
        r["faces"] = [f for f in r["faces"] if f.get("id")]
        r["unknown"] = [f for f in r["unknown"] if f.get("obs")]
        r["said"] = [u for u in r["said"] if u.get("id") and u.get("text")]
        r["people"] = sorted({f["id"] for f in r["faces"]})
        r["album"] = albums.get(r["path"])
        r["path"] = site.local(r["path"])
        r["date"] = r["date"] or ""
        out.append(r)
    out.sort(key=lambda m: m["date"])
    return out, {p["id"]: p for p in ppl}


def data() -> tuple[list[dict], dict]:
    """All moments and named people, reloaded at most every 10 s and only when the graph changed."""
    with _LOCK:
        if time.time() - _CACHE["at"] > 10:
            key = _version()
            if key != _CACHE["key"]:
                _CACHE["moments"], _CACHE["people"] = _load()
                _CACHE["key"] = key
            _CACHE["at"] = time.time()
        return _CACHE["moments"], _CACHE["people"]


def invalidate() -> None:
    with _LOCK:
        _CACHE["at"] = 0.0
        _CACHE["key"] = None


def owner() -> dict | None:
    _, ppl = data()
    return next((p for p in ppl.values() if p.get("owner")), None)


# ---------------- moments as cards ----------------

def card(m: dict, ppl: dict) -> dict:
    return {"id": m["id"], "sha": m["sha"], "kind": m["kind"], "date": m["date"][:10],
            "date_source": m["date_source"], "summary": m["summary"], "event": m["event"],
            "people": [{"id": pid, "name": ppl[pid]["name"]} for pid in m["people"] if pid in ppl],
            "unknown": len(m["unknown"]), "mood": m["mood"][:3], "place": m["place"],
            "duration": m["duration"], "w": m["width"], "h": m["height"], "words": len(m["said"])}


def moment(mid: str) -> dict | None:
    ms, ppl = data()
    m = next((x for x in ms if x["id"] == mid or x["sha"] == mid), None)
    if not m:
        return None
    c = card(m, ppl)
    c.update(date_why=m["date_why"], questions=m["questions"] or [], objects=m["objects"],
             activities=m["activities"], album=m["album"], place_type=m["place_type"],
             faces=[{"obs": f["obs"], "bbox": f["bbox"], "id": f["id"], "name": f["name"],
                     "by": f.get("by")} for f in m["faces"] if f.get("bbox")],
             unknown_faces=[{"obs": f["obs"], "bbox": f["bbox"],
                             "cand": ppl[f["cand"]]["name"] if f.get("cand") in ppl else None,
                             "cand_id": f.get("cand")} for f in m["unknown"]],
             said=[{"text": u["text"], "text_en": u.get("text_en"), "t0": u["t0"], "t1": u["t1"]}
                   for u in m["said"]],
             memory=memory_key(m))
    return c


# ---------------- memories ----------------

def memory_key(m: dict) -> str:
    """Moments that belong together: the album and year when the owner put them in an album (a childhood
    album is one memory per year, not one per photo; a trip album stays one memory even when some of its
    files kept a camera date), else the camera day."""
    if m["album"]:
        return f"album:{m['album']}:{m['date'][:4]}"
    return f"day:{m['date'][:10]}" if m["date"] else "undated"


def _titles() -> dict:
    try:
        return json.loads(TITLES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def memories() -> list[dict]:
    ms, ppl = data()
    groups: dict[str, list[dict]] = defaultdict(list)
    for m in ms:
        groups[memory_key(m)].append(m)
    titles = _titles()
    out = []
    for key, g in groups.items():
        who = Counter(pid for m in g for pid in m["people"])
        moods = Counter(x for m in g for x in m["mood"])
        # the cover: a picture with the most named people, then the most faces
        cover = max(g, key=lambda m: (m["kind"] != "audio", len(m["people"]), len(m["faces"]) + len(m["unknown"])))
        t = titles.get(key, {})
        out.append({"id": key, "title": t.get("title") or (g[0]["album"] if g[0]["album"] else None)
                    or (cover["event"] or "").capitalize() or "A moment",
                    "line": t.get("line") or cover["summary"],
                    "date": g[0]["date"][:10], "end": g[-1]["date"][:10],
                    "precise": all(m["date_source"] in ("exif", "container", "filename", "recorded") for m in g),
                    "count": len(g),
                    "videos": sum(1 for m in g if m["kind"] == "video"),
                    "cover": cover["sha"], "shas": [m["sha"] for m in g[:5]],
                    "people": [{"id": pid, "name": ppl[pid]["name"]} for pid, _ in who.most_common(6) if pid in ppl],
                    "mood": [x for x, _ in moods.most_common(2)], "place": next((m["place"] for m in g if m["place"]), None)})
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


def memory(key: str) -> dict | None:
    mem = next((x for x in memories() if x["id"] == key), None)
    if not mem:
        return None
    ms, ppl = data()
    mem["moments"] = [card(m, ppl) for m in ms if memory_key(m) == key]
    return mem


def on_this_day(today: date | None = None) -> list[dict]:
    """Memories from this week of the year in earlier years (precise dates only)."""
    today = today or date.today()
    out = []
    for mem in memories():
        if not mem["precise"]:
            continue
        try:
            d = date.fromisoformat(mem["date"])
        except ValueError:
            continue
        if d.year < today.year and abs((d.replace(year=today.year) - today).days) <= 7:
            out.append({**mem, "years_ago": today.year - d.year})
    return out


def write_titles(force: bool = False) -> int:
    """Muse Spark names every memory (a title and one warm line) from what the photos show. Cached by the
    memory's moments, so it reruns only for memories that changed."""
    from mlg.muse import chat
    ms, ppl = data()
    groups: dict[str, list[dict]] = defaultdict(list)
    for m in ms:
        groups[memory_key(m)].append(m)
    titles = _titles()
    todo = []
    for key, g in groups.items():
        sig = hashlib.md5("|".join(m["id"] for m in g).encode()).hexdigest()[:12]
        if not force and titles.get(key, {}).get("sig") == sig:
            continue
        todo.append((key, sig, g))
    schema = {"type": "object", "additionalProperties": False, "required": ["memories"],
              "properties": {"memories": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False, "required": ["id", "title", "line"],
                  "properties": {"id": {"type": "string"}, "title": {"type": "string"},
                                 "line": {"type": "string"}}}}}}
    for i in range(0, len(todo), 25):
        batch = todo[i:i + 25]
        payload = [{"id": key, "date": g[0]["date"][:10], "album": g[0]["album"],
                    "people": sorted({ppl[p]["name"] for m in g for p in m["people"] if p in ppl}),
                    "photos": [m["summary"] for m in g[:8]]} for key, _, g in batch]
        ans = chat.ask([chat.text(json.dumps(payload, ensure_ascii=False))], system=(
            "You title memories in a personal photo library. For each memory give a short title "
            "(2-6 words, like a photo album page: 'Lia's 7th birthday', 'Summer at the beach') and one warm, "
            "concrete line (max 16 words) about what the photos show. Use people's names when given. "
            "Never invent facts that the photo descriptions do not support. English."),
            schema=schema, schema_name="memory_titles", effort="low")
        sigs = {key: sig for key, sig, _ in batch}
        for t in ans.data.get("memories", []):
            if t.get("id") in sigs:
                titles[t["id"]] = {"title": t["title"], "line": t["line"], "sig": sigs[t["id"]]}
        TITLES.parent.mkdir(parents=True, exist_ok=True)
        TITLES.write_text(json.dumps(titles, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(todo)


# ---------------- timeline ----------------

def timeline() -> list[dict]:
    ms, ppl = data()
    years: dict[str, list[dict]] = defaultdict(list)
    for m in ms:
        if m["date"]:
            years[m["date"][:4]].append(m)
    out = []
    for y, g in sorted(years.items()):
        who = Counter(pid for m in g for pid in m["people"])
        cover = max(g, key=lambda m: (m["kind"] != "audio", len(m["people"])))
        out.append({"year": y, "count": len(g), "videos": sum(1 for m in g if m["kind"] == "video"),
                    "cover": cover["sha"], "people": [ppl[p]["name"] for p, _ in who.most_common(4) if p in ppl]})
    return out


def year(y: str) -> dict:
    ms, ppl = data()
    mems = [x for x in memories() if x["date"][:4] == y]
    mems.sort(key=lambda x: x["date"])
    return {"year": y, "memories": mems}


# ---------------- people and connections ----------------

def people_list() -> list[dict]:
    ms, ppl = data()
    seen = Counter(pid for m in ms for pid in m["people"])
    years: dict[str, list[str]] = defaultdict(list)
    for m in ms:
        for pid in m["people"]:
            if m["date"]:
                years[pid].append(m["date"][:4])
    out = [{"id": pid, "name": p["name"], "name_en": p.get("name_en"), "relation": p.get("relation"),
            "owner": bool(p.get("owner")),
            "count": seen.get(pid, 0), "from": min(years[pid]) if years[pid] else None,
            "to": max(years[pid]) if years[pid] else None} for pid, p in ppl.items()
           if seen.get(pid) or p.get("owner")]   # people named elsewhere but not in any picture here stay out
    out.sort(key=lambda p: (not p["owner"], -p["count"], p["name"]))
    return out


def person(pid: str) -> dict | None:
    ms, ppl = data()
    if pid not in ppl:
        return None
    mine = [m for m in ms if pid in m["people"]]
    pics, events = _pairs(ms)
    with_ = Counter()
    for (a, b), n in (pics + events).items():
        if pid in (a, b):
            with_[b if a == pid else a] += n
    by_year = Counter(m["date"][:4] for m in mine if m["date"])
    places = Counter(m["place"] for m in mine if m["place"])
    moods = Counter(x for m in mine for x in m["mood"])
    p = ppl[pid]
    return {"id": pid, "name": p["name"], "name_en": p.get("name_en"), "relation": p.get("relation"),
            "owner": bool(p.get("owner")), "count": len(mine), "videos": sum(1 for m in mine if m["kind"] == "video"),
            "years": sorted(by_year.items()),
            "with": [{"id": o, "name": ppl[o]["name"], "count": c} for o, c in with_.most_common(12) if o in ppl],
            "places": [x for x, _ in places.most_common(6)], "mood": [x for x, _ in moods.most_common(4)],
            "moments": [card(m, ppl) for m in reversed(mine)],
            "memories": [x for x in memories() if any(q["id"] == pid for q in x["people"])][:12]}


def graph() -> dict:
    """People as nodes, an edge where two people appear in the same picture (weight = how often).
    Memories they share hang off the edge, so a click on a line shows the pictures behind it."""
    ms, ppl = data()
    seen = Counter(pid for m in ms for pid in m["people"])
    pics, events = _pairs(ms)
    unknown = sum(len(m["unknown"]) for m in ms)
    keys = set(pics) | set(events)
    return {"nodes": [{"id": pid, "name": p["name"], "count": seen.get(pid, 0), "owner": bool(p.get("owner")),
                       "relation": p.get("relation")} for pid, p in ppl.items() if seen.get(pid)],
            "edges": [{"a": a, "b": b, "pics": pics.get((a, b), 0), "events": events.get((a, b), 0),
                       "w": pics.get((a, b), 0) + 0.5 * events.get((a, b), 0)} for a, b in keys],
            "unknown_faces": unknown}


def _pairs(ms: list[dict]) -> tuple[Counter, Counter]:
    """Two kinds of together: in the same picture, and at the same event (one memory) in different pictures."""
    pics: Counter = Counter()
    groups: dict[str, set] = defaultdict(set)
    for m in ms:
        ps = sorted(set(m["people"]))
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                pics[(ps[i], ps[j])] += 1
        groups[memory_key(m)].update(ps)
    events: Counter = Counter()
    for ps in groups.values():
        ps = sorted(ps)
        for i in range(len(ps)):
            for j in range(i + 1, len(ps)):
                events[(ps[i], ps[j])] += 1
    return pics, events


def shared(a: str, b: str) -> list[dict]:
    """Pictures of the two together, else the pictures of the events they were both at."""
    ms, ppl = data()
    both = [card(m, ppl) for m in ms if a in m["people"] and b in m["people"]]
    if both:
        return both
    keys_a = {memory_key(m) for m in ms if a in m["people"]}
    keys = {memory_key(m) for m in ms if b in m["people"]} & keys_a
    return [card(m, ppl) for m in ms if memory_key(m) in keys and (a in m["people"] or b in m["people"])]


def overview() -> dict:
    ms, ppl = data()
    me = owner()
    kinds = Counter(m["kind"] for m in ms)
    years = sorted({m["date"][:4] for m in ms if m["date"]})
    mems = memories()
    return {"owner": me["name"] if me else None, "owner_id": me["id"] if me else None,
            "photos": kinds.get("photo", 0), "videos": kinds.get("video", 0), "voice": kinds.get("audio", 0),
            "people": sum(1 for pid in ppl if any(pid in m["people"] for m in ms)), "memories": len(mems), "years": [years[0], years[-1]] if years else None,
            "unknown_faces": sum(len(m["unknown"]) for m in ms),
            "on_this_day": on_this_day()[:6], "recent": mems[:8],
            "untitled": sum(1 for x in mems if x["id"] not in _titles())}
