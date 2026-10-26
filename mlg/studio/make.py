"""One sentence -> a film.

    python -m mlg.studio.make "A 60-second film for grandma Ruth's 70th ..." [--dataset demo] [--height 720]

Writes data/films/<id>/ with storyboard.json (brief, script, crew log), edl.json
and film.mp4, and records the film in the graph (Film -> Scene -> Shot -> MediaItem).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from mlg.config import DATA
from mlg.graph.db import session
from mlg.studio import edit, render
from mlg.studio.plan import plan

FILMS = DATA / "films"


def record(film_id: str, storyboard: dict, edl: dict, path: Path) -> None:
    sc = storyboard["script"]
    scenes = [{"id": f"{film_id}:s{s['order']}", "order": s["order"], "intent": s["intent"],
               "line": s.get("narration"), "emotion": s.get("emotion"), "moments": s["moment_ids"]}
              for s in sc["scenes"]]
    shots = [{"id": f"{film_id}:shot{i}", "scene": f"{film_id}:s{s['scene']}", "kind": s["kind"],
              "start": s["start"], "dur": s["dur"], "media": s["moment"].split(":")[0]}
             for i, s in enumerate(edl["shots"])]
    with session() as s:
        s.run("""MERGE (f:Film {id: $id})
                 SET f.request = $req, f.title = $title, f.logline = $log, f.path = $path,
                     f.duration = $dur, f.created = $at, f.dataset = $ds
                 WITH f UNWIND $subjects AS pid MATCH (p:Person {id: pid}) MERGE (f)-[:FOR]->(p)""",
              id=film_id, req=storyboard["request"], title=sc["title"], log=sc["logline"], path=str(path),
              dur=edl["duration"], at=time.time(), ds=storyboard["dataset"],
              subjects=storyboard["brief"].get("subject_ids", [])).consume()
        s.run("""MATCH (f:Film {id: $id}) UNWIND $scenes AS x
                 MERGE (sc:Scene {id: x.id}) SET sc.order = x.order, sc.intent = x.intent, sc.line = x.line,
                                                 sc.emotion = x.emotion
                 MERGE (f)-[:HAS_SCENE]->(sc)
                 WITH sc, x UNWIND x.moments AS mid MATCH (m:Moment {id: mid}) MERGE (sc)-[:BASED_ON]->(m)""",
              id=film_id, scenes=scenes).consume()
        s.run("""UNWIND $shots AS x MATCH (sc:Scene {id: x.scene}), (mi:MediaItem {id: x.media})
                 MERGE (sh:Shot {id: x.id}) SET sh.kind = x.kind, sh.start = x.start, sh.dur = x.dur
                 MERGE (sc)-[:HAS_SHOT]->(sh) MERGE (sh)-[:USES]->(mi)""", shots=shots).consume()


def make(request: str, dataset: str = "demo", height: int = 720) -> dict:
    film_id = time.strftime("film_%Y%m%d_%H%M%S")
    out = FILMS / film_id
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    sb = plan(request, dataset)
    (out / "storyboard.json").write_text(json.dumps(sb, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    t1 = time.perf_counter()
    edl = edit.build(sb)
    (out / "edl.json").write_text(json.dumps(edl, ensure_ascii=False, indent=1), encoding="utf-8")
    path = render.render(edl, out, height, seed=int(time.time()) % 1000)
    t2 = time.perf_counter()
    record(film_id, sb, edl, path)
    return {"film": film_id, "path": str(path), "duration_s": edl["duration"], "shots": len(edl["shots"]),
            "plan_s": round(t1 - t0, 1), "render_s": round(t2 - t1, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("request")
    ap.add_argument("--dataset", default="demo")
    ap.add_argument("--height", type=int, default=720)
    a = ap.parse_args()
    print(json.dumps(make(a.request, a.dataset, a.height), ensure_ascii=False))


if __name__ == "__main__":
    main()
