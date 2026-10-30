"""One sentence -> a film, made by the crew and revised once after the critic watches it.

    python -m mlg.studio.make "A 60-second film for grandma Ruth's 70th ..." [--dataset real]

Pipeline (each step reports to the crew log the Edit Room shows live):
  Researcher -> Producer -> Screenwriter -> script check -> Picture Checker -> Editor
  -> draft v1 (480p) -> Critic watches v1 -> Editor applies the notes -> v2 (720p) -> Critic scores v2
Everything lands in data/films/<id>/ (state.json, storyboard.json, edl_v1/v2.json, v1/, v2/)
and the film is recorded in the graph (Film -> Scene -> Shot -> MediaItem).
"""
from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path
from typing import Callable

from mlg.config import DATA
from mlg.graph.db import session
from mlg.people import roster
from mlg.studio import ask, checker, critic, edit, render, sound
from mlg.studio.plan import plan

FILMS = DATA / "films"


class Job:
    """Film state on disk; every update is visible to the Edit Room immediately."""

    def __init__(self, film_id: str, request: str, dataset: str):
        self.dir = FILMS / film_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state = {"id": film_id, "request": request, "dataset": dataset, "status": "running",
                      "created": time.time(), "log": [], "versions": {}, "error": None}
        self.save()

    def save(self) -> None:
        tmp = self.dir / "state.tmp"
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        tmp.replace(self.dir / "state.json")

    def say(self, who: str, did: str, why: str = "", **extra) -> None:
        self.state["log"].append({"t": round(time.time() - self.state["created"], 1), "who": who, "did": did,
                                  "why": why, **extra})
        self.save()

    def put(self, name: str, obj) -> None:
        (self.dir / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def record(film_id: str, storyboard: dict, edl: dict, path: Path, scores: dict) -> None:
    sc = storyboard["script"]
    scenes = [{"id": f"{film_id}:s{s['order']}", "order": s["order"], "intent": s["intent"],
               "line": s.get("narration"), "emotion": s.get("emotion"), "moments": s["moment_ids"]}
              for s in sc["scenes"]]
    shots = [{"id": f"{film_id}:shot{i}", "scene": f"{film_id}:s{s['scene']}", "kind": s["kind"],
              "start": s["start"], "dur": s["dur"], "media": s["moment"].split(":")[0]}
             for i, s in enumerate(edl["shots"])]
    with session() as s:
        s.run("""MERGE (f:Film {id: $id})
                 SET f.request = $req, f.title = $title, f.logline = $log, f.path = $path, f.duration = $dur,
                     f.created = $at, f.dataset = $ds, f.score_v1 = $s1, f.score_v2 = $s2
                 WITH f UNWIND $subjects AS pid MATCH (p:Person {id: pid}) MERGE (f)-[:FOR]->(p)""",
              id=film_id, req=storyboard["request"], title=sc["title"], log=sc["logline"], path=str(path),
              dur=edl["duration"], at=time.time(), ds=storyboard["dataset"], s1=scores.get("v1"),
              s2=scores.get("v2"), subjects=storyboard["brief"].get("subject_ids", [])).consume()
        s.run("""MATCH (f:Film {id: $id}) UNWIND $scenes AS x
                 MERGE (sc:Scene {id: x.id}) SET sc.order = x.order, sc.intent = x.intent, sc.line = x.line,
                                                 sc.emotion = x.emotion
                 MERGE (f)-[:HAS_SCENE]->(sc)
                 WITH sc, x UNWIND x.moments AS mid MATCH (m:Moment {id: mid}) MERGE (sc)-[:BASED_ON]->(m)""",
              id=film_id, scenes=scenes).consume()
        s.run("""UNWIND $shots AS x MATCH (sc:Scene {id: x.scene}), (mi:MediaItem {id: x.media})
                 MERGE (sh:Shot {id: x.id}) SET sh.kind = x.kind, sh.start = x.start, sh.dur = x.dur
                 MERGE (sc)-[:HAS_SHOT]->(sh) MERGE (sh)-[:USES]->(mi)""", shots=shots).consume()


def sound_up(job: Job, sb: dict, edl: dict, seed: int, version: str) -> None:
    """Narrator + composer for one cut. Any GPU failure falls back to the placeholder score."""
    try:
        t = time.perf_counter()
        n = sound.narrate(edl, sb["brief"].get("language", "en"))
        edit.retime(edl)
        if n:
            job.say("Narrator", f"voiced {n} narration lines ({version})", "Meta SeamlessM4T v2 on the local GPU",
                    seconds=round(time.perf_counter() - t, 1))
        first = "score_plan" not in sb
        t = time.perf_counter()
        sc = sound.score(sb, edl, seed)
        if sc:
            edl["score_path"] = sc["path"]
            if first:
                job.say("Sound designer", f"{len(sb['score_plan']['cues'])} music cues", sb["score_plan"]["why"],
                        cues=[c["prompt"] for c in sb["score_plan"]["cues"]])
            if sc.get("reused"):
                job.say("Composer", f"{version} keeps the same score", "the edited cut still fits inside it")
            else:
                job.say("Composer", f"score for {version}: {len(sc['cues'])} MusicGen clips, crossfaded",
                        "Meta MusicGen (medium) on the local GPU", seconds=round(time.perf_counter() - t, 1))
    except Exception as e:  # noqa: BLE001 - a film without the new score is better than no film
        edl.pop("score_path", None)
        job.say("Composer", "fell back to the placeholder score", f"{type(e).__name__}: {e}"[:300])


def _scenes(sb: dict) -> list[dict]:
    return [{"order": s["order"], "beat": s.get("beat"), "intent": s["intent"], "narration": s.get("narration"),
             "emotion": s.get("emotion"), "moments": list(s["moment_ids"])} for s in sb["script"]["scenes"]]


def make(request: str, dataset: str = "real", film_id: str | None = None,
         on_start: Callable[[str], None] | None = None, template: str | None = None,
         ask_wait: float = 0) -> dict:
    """ask_wait: seconds the crew waits for the owner's answers (0 = don't ask, use the crew's picks)."""
    film_id = film_id or time.strftime("film_%Y%m%d_%H%M%S")
    job = Job(film_id, request, dataset)
    job.state["timing"] = {}
    if on_start:
        on_start(film_id)
    try:
        job.say("Producer", "reading the request", request)
        sb = plan(request, dataset, template)
        for entry in sb["crew_log"]:
            job.say(entry["who"], entry["did"], entry.get("why", ""))
        job.state["title"] = sb["script"]["title"]
        job.state["brief"] = sb["brief"]
        job.state["scenes"] = _scenes(sb)

        qs = ask.questions(sb, roster(dataset))
        if qs:
            if ask_wait > 0:
                job.say("Director", f"pausing to ask you {len(qs)} question{'s' * (len(qs) > 1)}",
                        " / ".join(q["text"] for q in qs))
            t = time.perf_counter()
            answers = ask.wait(job, qs, ask_wait)
            job.state["timing"]["waiting_for_owner"] = round(time.perf_counter() - t, 1)
            done = ask.apply(sb, qs, answers)
            job.state["questions"] = qs
            job.state["scenes"] = _scenes(sb)
            job.say("Director", f"{sum(q['answer'] != ask.NOBODY for q in qs)} of {len(qs)} answered",
                    "; ".join(done))

        job.say("Picture Checker", "looking at every picture of every scene")
        notes = checker.check(sb)
        job.state["picture_check"] = {k: {"note": v["note"], "verdicts": v["verdicts"],
                                          "narration_fix": v.get("narration_fix") if not v["narration_ok"] else None}
                                      for k, v in sb["picture_check"].items()}
        job.say("Picture Checker", f"{len(notes)} changes" if notes else "every picture fits its scene",
                "; ".join(notes))
        job.put("storyboard.json", sb)

        edl1 = edit.build(sb)
        seed = int(time.time()) % 1000
        sound_up(job, sb, edl1, seed, "v1")
        job.put("edl_v1.json", edl1)
        job.say("Editor", f"{len(edl1['shots'])} shots, {edl1['duration']:.0f} s, {edl1['aspect']}",
                "camera drifts toward the person each scene is about; voices never cut")
        job.say("Renderer", "rendering draft v1 (480p)")
        t = time.perf_counter()
        v1 = render.render(edl1, job.dir / "v1", 480, seed=seed)
        job.state["versions"]["v1"] = {"path": str(v1), "duration": edl1["duration"]}
        job.say("Renderer", f"draft v1 ready in {time.perf_counter() - t:.0f} s")

        job.say("Critic", "watching draft v1")
        c1 = critic.watch(v1, edl1, sb["brief"])
        job.put("critique_v1.json", c1)
        job.state["versions"]["v1"].update(score=c1["score"], summary=c1["summary"], notes=c1["notes"])
        job.say("Critic", f"v1 scored {c1['score']}/10", c1["summary"])

        edl2, applied = critic.apply(copy.deepcopy(edl1), c1)
        job.state["applied"] = applied
        job.say("Editor", f"applied {len(applied)} of {len(c1['notes'])} notes", "; ".join(applied))
        sound_up(job, sb, edl2, seed, "v2")
        job.put("edl_v2.json", edl2)
        job.say("Renderer", "rendering v2 (720p)")
        t = time.perf_counter()
        v2 = render.render(edl2, job.dir / "v2", 720, seed=seed)
        job.state["versions"]["v2"] = {"path": str(v2), "duration": edl2["duration"]}
        job.say("Renderer", f"v2 ready in {time.perf_counter() - t:.0f} s")

        job.say("Critic", "watching v2")
        c2 = critic.watch(v2, edl2, sb["brief"])
        job.put("critique_v2.json", c2)
        job.state["versions"]["v2"].update(score=c2["score"], summary=c2["summary"], notes=c2["notes"])
        job.say("Critic", f"v2 scored {c2['score']}/10 (v1 was {c1['score']})", c2["summary"])

        record(film_id, sb, edl2, v2, {"v1": c1["score"], "v2": c2["score"]})
        job.state["status"] = "done"
        job.state["finished"] = time.time()
        job.save()
    except Exception as e:  # noqa: BLE001 - surface the failure in the Edit Room
        job.state["status"] = "failed"
        job.state["error"] = f"{type(e).__name__}: {e}"[:600]
        job.save()
        raise
    return job.state


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("request")
    ap.add_argument("--dataset", default="real")
    ap.add_argument("--template", choices=["birthday", "wedding", "friends", "family"])
    ap.add_argument("--ask-wait", type=float, default=0,
                    help="seconds to wait for answers in the Edit Room (0 = the crew decides)")
    a = ap.parse_args()
    st = make(a.request, a.dataset, template=a.template, ask_wait=a.ask_wait)
    print(json.dumps({"film": st["id"], "v1": st["versions"]["v1"].get("score"),
                      "v2": st["versions"]["v2"].get("score")}))


if __name__ == "__main__":
    main()
