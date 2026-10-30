"""Seed the people of this graph from the owner's earlier Life Graph (their own data, read-only).

    python scripts/seed_from_lifegraph.py people            # names + reference faces, no Muse calls
    python scripts/seed_from_lifegraph.py attrs             # groups, family branch, relationship, English name
    python scripts/seed_from_lifegraph.py demo              # ~30 people, ~3,000 photos + videos, read in place
    python scripts/seed_from_lifegraph.py look [--limit N]  # Muse looks at the photos the earlier graph knows
    python scripts/seed_from_lifegraph.py link [--dry]      # name faces Muse found, when two keys agree
    python scripts/seed_from_lifegraph.py undo              # remove every link this script made

The earlier graph (a local Neo4j, settings in its .env) knows who the owner's people are:
a name, one face picture, and which photos each person is in (but not where in the photo).
`people` makes each named person here with reference faces: that picture plus up to 12 faces
from photos where the earlier graph saw only that person, spread over the years and kept only
when they look like the person's own picture. It also remembers, per Facebook photo id, who the
earlier graph saw in it - the two imports come from the same export, so the ids match.

`link` then names a face Muse found when the face fingerprint matches the person AND either the
earlier graph saw that person in the same photo, or the match is very strong and clearly better
than anyone else. Links are marked confirmed_by='lifegraph' and `undo` removes them all.
Nothing is read from or written to the earlier graph's code; only its data is used, on the
owner's own computer.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from dotenv import dotenv_values  # noqa: E402
from neo4j import GraphDatabase  # noqa: E402
from PIL import Image  # noqa: E402

from mlg import faces, identity, library  # noqa: E402
from mlg.config import CACHE, DATA  # noqa: E402
from mlg.graph.db import session  # noqa: E402

OLD = Path(os.environ.get("LIFEGRAPH_DIR", r"C:\Users\agmon\projects\lifegraph-beinspace-20260916"))
OWNER_OLD_ID = os.environ.get("LIFEGRAPH_OWNER", "face_1398")   # the owner in the earlier graph
OWNER_NEW_ID = "person:agmon"
MIN_PHOTOS = 5
SOLO_REFS = 12
PHOTO_MAP = CACHE / "lifegraph_photo_people.json"
CROPS = DATA / "people"
LINK_WITH_PHOTO = 0.50     # fingerprint match + the earlier graph saw them in this photo
LINK_ALONE = 0.62          # fingerprint match alone, also needs a clear margin over the next person
MARGIN = 0.10


def old_driver():
    e = dotenv_values(OLD / ".env")
    return GraphDatabase.driver(e["NEO4J_URI"], auth=(e["NEO4J_USER"], e["NEO4J_PASSWORD"]))


def fb_id(path: str) -> str:
    """Facebook's own photo id: the earlier import named files FB_<date>_<time>_<id>.jpg, this one <id>.jpg."""
    return Path(path).stem.split("_")[-1]


def new_id(old_id: str) -> str:
    return OWNER_NEW_ID if old_id == OWNER_OLD_ID else f"person:lg-{old_id}"


def _face_crop(img: Image.Image) -> tuple[Image.Image, np.ndarray] | None:
    """The single clear face in a photo, cropped head-and-shoulders, with its fingerprint."""
    import cv2
    rgb = np.asarray(img.convert("RGB"))
    h, w = rgb.shape[:2]
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    with faces._LOCK:
        det, rec = faces._nets()
        det.setInputSize((w, h))
        _, found = det.detect(bgr)
        if found is None:
            return None
        found = [f for f in found if f[14] >= 0.8 and min(f[2], f[3]) >= 50]
        if len(found) != 1:
            return None
        f = found[0]
        v = rec.feature(rec.alignCrop(bgr, f)).flatten().astype(np.float32)
    x, y, fw, fh = (float(t) for t in f[:4])
    box = (max(0, x - fw * .45), max(0, y - fh * .5), min(w, x + fw * 1.45), min(h, y + fh * 1.5))
    crop = img.crop(tuple(int(t) for t in box))
    crop.thumbnail((384, 384))
    return crop, v / (np.linalg.norm(v) + 1e-9)


def seed_people() -> None:
    drv = old_driver()
    with drv.session() as s:
        people = s.run("""MATCH (p:Person)-[a:APPEARS_IN]->(:Event)
                          WHERE p.name IS NOT NULL AND NOT p.name STARTS WITH 'unknown' AND coalesce(p.hidden, false) = false
                          WITH p, count(a) AS c WHERE c >= $n RETURN p.id AS id, p.name AS name, c ORDER BY c DESC""",
                       n=MIN_PHOTOS).data()
        ids = [p["id"] for p in people]
        solo = s.run("""UNWIND $ids AS pid MATCH (p:Person {id: pid})-[:APPEARS_IN]->(ev:Event)
                        WITH p, ev MATCH (q:Person)-[:APPEARS_IN]->(ev) WITH p, ev, count(q) AS n WHERE n = 1
                        RETURN p.id AS pid, ev.id AS ev, ev.taken_at AS t""", ids=ids).data()
        fb = s.run("""MATCH (p:Person)-[:APPEARS_IN]->(ev:Event) WHERE ev.source_path CONTAINS 'facebook'
                      AND p.id IN $ids RETURN ev.source_path AS path, collect(DISTINCT p.id) AS who""", ids=ids).data()
    by_person = defaultdict(list)
    for r in solo:
        by_person[r["pid"]].append(r)
    con = faces._con()
    made = refs_total = 0
    for p in people:
        own = OLD / "data" / "faces" / f"{p['id']}.png"
        if not own.exists():
            continue
        anchor = faces.embed(Image.open(own))
        crops: list[tuple[Image.Image, np.ndarray]] = []
        if anchor:
            img = Image.open(own).convert("RGB")
            crops.append((img, anchor[0]))
        # solo photos spread over the years: every k-th one in date order
        evs = sorted(by_person[p["id"]], key=lambda r: r["t"] or "")
        step = max(1, len(evs) // (SOLO_REFS * 3))
        for r in evs[::step]:
            if len(crops) > SOLO_REFS:
                break
            small = OLD / "data" / "photos_small" / r["ev"][:2] / f"{r['ev']}.jpg"
            if not small.exists():
                continue
            got = _face_crop(Image.open(small))
            # the earlier graph's own links can be wrong: keep faces that look like the person's picture
            if got and (anchor is None or float(got[1] @ anchor[0]) >= 0.30):
                crops.append(got)
        if not crops:
            continue
        pid = new_id(p["id"])
        folder = CROPS / pid.replace(":", "_")
        folder.mkdir(parents=True, exist_ok=True)
        paths = []
        for k, (img, v) in enumerate(crops):
            out = folder / f"lg_{k:02d}.jpg"
            img.convert("RGB").save(out, quality=88)
            con.execute("INSERT OR REPLACE INTO vec VALUES (?,?,?,?)", (f"ref:{out}", v.tobytes(), 1.0, 0))
            paths.append(str(out))
        con.commit()
        with session() as s:
            if pid == OWNER_NEW_ID:
                s.run("""MATCH (p:Person {id: $id}) SET p.ref_crops = coalesce(p.ref_crops, []) + $more,
                         p.name_he = $name, p.source_lifegraph = $old""", id=pid, more=paths, name=p["name"],
                      old=p["id"]).consume()
            else:
                s.run("""MERGE (p:Person {id: $id})
                         SET p.name = $name, p.confirmed = true, p.dataset = 'real', p.is_owner = false,
                             p.ref_crop = $first, p.ref_crops = $more, p.source_lifegraph = $old""",
                      id=pid, name=p["name"], first=paths[0], more=paths[1:], old=p["id"]).consume()
        made += 1
        refs_total += len(paths)
        print(f"{made:4} {p['name']}: {len(paths)} reference faces", flush=True)
    photo_map = defaultdict(list)
    for r in fb:
        photo_map[fb_id(r["path"])].extend(new_id(w) for w in r["who"])
    PHOTO_MAP.write_text(json.dumps(photo_map, ensure_ascii=False), encoding="utf-8")
    library.invalidate()
    print(f"people {made}, reference faces {refs_total}, Facebook photos with known people {len(photo_map)}")


def link(dry: bool) -> None:
    photo_map = json.loads(PHOTO_MAP.read_text(encoding="utf-8")) if PHOTO_MAP.exists() else {}
    faces.index()
    con = faces._con()
    obs = faces._observations()
    people = faces._people_vectors(con, obs)
    open_ = [o for o in obs if not o["person"] and not o["action"]]
    vecs = faces._vectors(con, [o["id"] for o in open_])
    # per photo: every face scored against every person, then the best pairs first - one face per person
    # and one person per face in a photo (the earlier graph says who is in it, not which face)
    by_photo = defaultdict(list)
    for o in open_:
        if o["id"] in vecs:
            by_photo[o["sha"]].append(o)
    n_photo = n_alone = 0
    for sha, group in by_photo.items():
        here = set(photo_map.get(fb_id(group[0]["path"]), []))
        pairs = []
        for o in group:
            v = vecs[o["id"]]
            scores = sorted(((float(np.mean(np.sort(m @ v)[-3:])), pid) for pid, m in people.items()), reverse=True)
            if not scores:
                continue
            second = scores[1][0] if len(scores) > 1 else 0.0
            for sc, pid in scores[:8]:
                if pid in here and sc >= LINK_WITH_PHOTO:
                    pairs.append((sc, o, pid, "photo", second))
                elif sc == scores[0][0] and sc >= LINK_ALONE and sc - second >= MARGIN:
                    pairs.append((sc, o, pid, "alone", second))
        used_faces, used_people = set(), set()
        for sc, o, pid, how, second in sorted(pairs, key=lambda t: -t[0]):
            if o["id"] in used_faces or pid in used_people:
                continue
            used_faces.add(o["id"])
            used_people.add(pid)
            n_photo += how == "photo"
            n_alone += how == "alone"
            if dry:
                continue
            with session() as s:
                s.run("""MATCH (o:Observation {id: $oid}), (p:Person {id: $pid})
                         MERGE (p)-[r:OBSERVED_AS]->(o)
                         SET r.confidence = $c, r.confirmed_by = 'lifegraph', r.rationale = $why""",
                      oid=o["id"], pid=pid, c=round(sc, 3),
                      why=f"face match {sc:.2f}" + (" and the earlier Life Graph saw them in this photo" if how == "photo"
                                                    else f", next person {second:.2f}")).consume()
            identity.record(o["id"], "auto", pid)
    library.invalidate()
    print(f"{'would link' if dry else 'linked'}: {n_photo} with the photo as second key, {n_alone} by a strong match alone")


def demo(people_n: int, per_person: int, cap: int, videos: int) -> None:
    """A demo library from the earlier graph: the owner's closest people, photos of each spread over the
    years, the other photos of the same days, and some videos. Files are read in place (the earlier
    graph's reduced copies on C:, videos from the phone folder); dates come from the earlier graph."""
    from mlg.ingest.scan import connect, ingest_file, mark_duplicates
    drv = old_driver()
    with drv.session() as s:
        top = s.run("""MATCH (p:Person)-[a:APPEARS_IN]->(ev:Event) WHERE p.name IS NOT NULL AND NOT p.name STARTS WITH 'unknown'
                       AND coalesce(p.hidden, false) = false AND ev.source_path IS NOT NULL
                       WITH p, count(DISTINCT ev) AS c ORDER BY c DESC LIMIT $n RETURN p.id AS id""", n=people_n).data()
        ids = [r["id"] for r in top]
        evs = s.run("""MATCH (p:Person)-[:APPEARS_IN]->(ev:Event) WHERE p.id IN $ids
                       RETURN ev.id AS id, ev.taken_at AS t, ev.source_path AS path, ev.video_path AS video,
                              ev.taken_at_source AS src, collect(DISTINCT p.id) AS who""", ids=ids).data()
    small = OLD / "data" / "photos_small"

    def file_of(e):
        if e["video"]:
            return Path(e["video"]) if Path(e["video"]).exists() else None
        f = small / e["id"][:2] / f"{e['id']}.jpg"
        return f if f.exists() else None

    evs = [e for e in evs if e["t"] and file_of(e)]
    by_id = {e["id"]: e for e in evs}
    chosen: dict[str, dict] = {}
    for pid in ids:
        mine = sorted((e for e in evs if pid in e["who"] and not e["video"]), key=lambda e: e["t"])
        # spread over the years: the photos with the most of the chosen people first, a few from each year
        years = defaultdict(list)
        for e in mine:
            years[e["t"][:4]].append(e)
        per_year = max(1, per_person // max(1, len(years)))
        for y, es in years.items():
            for e in sorted(es, key=lambda e: -len(e["who"]))[:per_year]:
                chosen[e["id"]] = e
    days = defaultdict(list)
    for e in evs:
        days[e["t"][:10]].append(e)
    for d in sorted({e["t"][:10] for e in chosen.values()}):
        for e in days[d]:
            if len(chosen) >= cap:
                break
            if not e["video"]:
                chosen.setdefault(e["id"], e)
    vids = sorted((e for e in evs if e["video"]), key=lambda e: (-len(e["who"]), e["t"]))[:videos]
    for e in vids:
        chosen[e["id"]] = e
    print(f"people {len(ids)}, photos {sum(1 for e in chosen.values() if not e['video'])}, videos {len(vids)}", flush=True)
    con = connect()
    photo_map = json.loads(PHOTO_MAP.read_text(encoding="utf-8")) if PHOTO_MAP.exists() else {}
    for n, e in enumerate(chosen.values(), 1):
        f = file_of(e)
        ingest_file(con, f)
        # a time of day means the camera kept it; midnight/noon dates were estimated by the earlier graph
        exact = len(e["t"]) > 10 and e["t"][11:19] not in ("00:00:00", "12:00:00")
        con.execute("UPDATE items SET taken_at=?, date_source=? WHERE path=?",
                    (e["t"][:19], (e["src"] or "exif") if exact else "content", str(f)))
        photo_map[fb_id(str(f))] = [new_id(w) for w in e["who"]]
        if n % 200 == 0:
            con.commit()
            print(f"{n}/{len(chosen)}", flush=True)
    con.commit()
    PHOTO_MAP.write_text(json.dumps(photo_map, ensure_ascii=False), encoding="utf-8")
    print(f"brought in {len(chosen)}, copies set aside {mark_duplicates(con)}", flush=True)


def look(limit: int | None, source: str | None = None, workers: int | None = None) -> None:
    """Muse looks at the Facebook photos the earlier graph knows people in. Each call carries only the
    reference faces of the people likely to be there (those, else the owner), not the whole roster."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from mlg import imports
    from mlg.people import roster
    from mlg.perceive.run import perceive_item
    photo_map = json.loads(PHOTO_MAP.read_text(encoding="utf-8"))
    everyone = {p["id"]: p for p in roster("real")}
    refs = faces._all_refs()
    with session() as s:
        names = {r["id"]: r for r in s.run("MATCH (p:Person {confirmed: true}) RETURN p.id AS id, p.name AS name, "
                                           "p.relation AS relation, p.note AS note").data()}

    def person(pid):
        p = everyone.get(pid) or {**names.get(pid, {"id": pid, "name": pid}), "crops": refs.get(pid, [])}
        return {**p, "crops": refs.get(pid, p.get("crops", []))}

    items = [it for it in imports._waiting_items() if fb_id(it["path"]) in photo_map
             and (not source or (source[1:].lower() not in it["path"].lower() if source.startswith("!")
                                 else source.lower() in it["path"].lower()))][:limit]
    print(f"{len(items)} items", flush=True)
    done = failed = 0
    with ThreadPoolExecutor(workers or imports.WORKERS) as ex:
        futs = {ex.submit(perceive_item, it, [person(p) for p in (photo_map[fb_id(it["path"])][:6] or [OWNER_NEW_ID])]): it
                for it in items}
        for f in as_completed(futs):
            try:
                f.result()
                done += 1
            except Exception as e:  # noqa: BLE001 - one bad file must not stop the rest
                failed += 1
                print("FAIL", futs[f]["path"], str(e)[:200], flush=True)
            if (done + failed) % 25 == 0:
                print(f"{done + failed}/{len(items)}", flush=True)
    library.invalidate()
    print(f"done {done}, failed {failed}", flush=True)


FAMILY_GROUP = {"Nuclear Family": "המשפחה הגרעינית", "Extended Family": "משפחה מורחבת", "Tobi Family": "טובי'ס"}


def attrs() -> None:
    """What the owner already said about each person in the earlier graph: their groups (set by hand), the
    family branch, the relationship to the owner and an English name. Data only; read-only there."""
    with session() as s:
        here = s.run("MATCH (p:Person) WHERE p.source_lifegraph IS NOT NULL RETURN p.id AS id, p.source_lifegraph AS old").data()
    by_old = {r["old"]: r["id"] for r in here}
    with old_driver().session() as s:
        rows = s.run("""MATCH (p:Person) WHERE p.id IN $ids RETURN p.id AS id, p.groups_manual AS groups,
                        p.family_group AS family, p.relationship AS rel, p.name_en AS en, p.birth_year AS born""",
                     ids=list(by_old)).data()
    n = 0
    with session() as s:
        for r in rows:
            groups = list(r["groups"] or []) or ([FAMILY_GROUP.get(r["family"], r["family"])] if r["family"] else [])
            s.run("""MATCH (p:Person {id: $id}) SET p.groups = $groups, p.relation = coalesce($rel, p.relation),
                     p.name_en = $en, p.birth_year = $born""",
                  id=by_old[r["id"]], groups=groups, rel=r["rel"], en=r["en"], born=r["born"]).consume()
            n += bool(groups)
    library.invalidate()
    print(f"people updated {len(rows)}, with a group {n}")


def undo() -> None:
    with session() as s:
        n = s.run("MATCH (:Person)-[r:OBSERVED_AS {confirmed_by: 'lifegraph'}]->(o) "
                  "WITH r, o.id AS oid DELETE r RETURN collect(oid) AS ids").single()["ids"]
    con = identity._con()
    con.executemany("DELETE FROM identity WHERE obs_id=? AND action='auto'", [(i,) for i in n])
    con.commit()
    library.invalidate()
    print(f"removed {len(n)} links")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["people", "attrs", "demo", "look", "link", "undo"])
    ap.add_argument("--people", type=int, default=30)
    ap.add_argument("--per", type=int, default=40)
    ap.add_argument("--cap", type=int, default=3000)
    ap.add_argument("--videos", type=int, default=80)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--source", help="only files whose path contains this (e.g. facebook); !facebook = all but those")
    ap.add_argument("--workers", type=int)
    a = ap.parse_args()
    {"people": seed_people, "attrs": attrs, "demo": lambda: demo(a.people, a.per, a.cap, a.videos), "look": lambda: look(a.limit, a.source, a.workers), "link": lambda: link(a.dry), "undo": undo}[a.cmd]()
