"""Pause and ask: the crew stops before cutting when only the owner can know the answer.

Two kinds of question, at most MAX_QUESTIONS per film, each shown with pictures:
  identity - a face in a picture the film uses that the archive could not name
             ("Is this young woman in the 1990s scan Ruth?"). Yes links the face in the
             graph for good (the same path as the "Who is this?" screen).
  pick     - the screenwriter was torn between pictures for a key scene and listed
             a doubt ("Which picture should be the peak?").
Each question has a default (the crew's pick); if nobody answers within the wait,
the crew goes with it and says so in the log.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from mlg import identity

MAX_QUESTIONS = 3
MIN_FACE_AREA = 0.03      # share of the picture; smaller faces are background people
NOBODY = "__crew__"       # answer value for "let the crew decide"


def _area(bbox: list) -> float:
    x1, y1, x2, y2 = (list(bbox) + [0, 0, 0, 0])[:4]
    return abs((x2 - x1) * (y2 - y1)) / 1e6


def questions(sb: dict, roster: list[dict]) -> list[dict]:
    ms, script = sb["moments"], sb["script"]
    names = {p["id"]: p["name"] for p in roster}
    subjects = sb["brief"].get("subject_ids", [])
    out: list[dict] = []
    seen = set()
    # identity: unnamed, clearly visible faces in the film's pictures; the honoree's candidates first
    faces = []
    for sc in script["scenes"]:
        for mid in sc["moment_ids"]:
            m = ms[mid]
            for f in m.get("unknown", []):
                if f["obs"] in seen or _area(f.get("bbox") or []) < MIN_FACE_AREA:
                    continue
                seen.add(f["obs"])
                faces.append((f.get("candidate") not in subjects, f.get("candidate") is None,
                              -_area(f["bbox"]), sc, m, f))
    for *_, sc, m, f in sorted(faces, key=lambda x: x[:3]):
        cand = f.get("candidate") if f.get("candidate") in names else None
        year = (m.get("date") or "")[:4]
        opts = ([{"value": cand, "label": f"Yes, {names[cand]}"}] if cand else []) + \
               [{"value": pid, "label": n} for pid, n in names.items() if pid != cand][:5] + \
               [{"value": "other", "label": "Someone else"}]
        out.append({"id": f"q{len(out) + 1}", "kind": "identity", "scene": sc["order"], "moment": m["id"],
                    "obs": f["obs"],
                    "text": (f"Is this {names[cand]}?" if cand else "Who is this?") +
                            (f" ({m['kind']} from {year})" if year else ""),
                    "why": f"the scene \"{sc['intent'][:80]}\" uses this picture, and the archive could not "
                           f"name the face ({(f.get('appearance') or '')[:70]})",
                    "image": f"/api/crop/{f['obs']}", "context_image": f"/api/photo/{m['id'].split(':')[0]}",
                    "options": opts, "default": NOBODY})
        if len(out) >= 2:
            break
    # pick: the screenwriter's own doubts
    for d in script.get("doubts", [])[: MAX_QUESTIONS - len(out)]:
        sc = next((s for s in script["scenes"] if s["order"] == d.get("scene_order")), None)
        opts = [o for o in d.get("options", []) if o.get("moment_id") in ms]
        if not sc or len(opts) < 2:
            continue
        default = d.get("chosen_moment_id") if d.get("chosen_moment_id") in sc["moment_ids"] else \
            next((o["moment_id"] for o in opts if o["moment_id"] in sc["moment_ids"]), opts[0]["moment_id"])
        out.append({"id": f"q{len(out) + 1}", "kind": "pick", "scene": sc["order"], "text": d["question"],
                    "why": d.get("why") or "", "default": default,
                    "options": [{"value": o["moment_id"], "label": o.get("label") or "",
                                 "image": f"/api/photo/{o['moment_id'].split(':')[0]}"} for o in opts]})
    return out[:MAX_QUESTIONS]


def wait(job, qs: list[dict], seconds: float) -> dict[str, str]:
    """Shows the questions in the Edit Room and waits for answers (answers.json, written by the web app)."""
    if not qs or seconds <= 0:
        return {}
    path: Path = job.dir / "answers.json"
    job.state.update(questions=qs, status="waiting", waiting_until=time.time() + seconds)
    job.save()
    deadline = time.time() + seconds
    answers: dict[str, str] = {}
    while time.time() < deadline:
        if path.exists():
            try:
                answers = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                answers = {}
            if all(q["id"] in answers for q in qs):
                break
        time.sleep(1.0)
    job.state.update(status="running", waiting_until=None)
    job.save()
    return answers


def apply(sb: dict, qs: list[dict], answers: dict[str, str]) -> list[str]:
    """Carry out each answer on the storyboard (and the graph, for identities). Returns log lines."""
    ms, scenes = sb["moments"], sb["script"]["scenes"]
    log = []
    for q in qs:
        a = answers.get(q["id"], NOBODY)
        q["answer"] = a
        sc = next((s for s in scenes if s["order"] == q["scene"]), None)
        if a == NOBODY:
            q["outcome"] = "no answer - the crew decided"
            if q["kind"] == "pick":
                q["outcome"] += " (kept its own pick)"
            log.append(f"{q['text']} - {q['outcome']}")
            continue
        if q["kind"] == "identity":
            m = ms[q["moment"]]
            face = next((f for f in m.get("unknown", []) if f["obs"] == q["obs"]), None)
            if a == "other":
                q["outcome"] = "not who the crew thought"
                if sc and q["moment"] in sc["moment_ids"] and \
                        sum(ms[x]["kind"] in ("photo", "video") for x in sc["moment_ids"]) > 1:
                    sc["moment_ids"].remove(q["moment"])   # the scene was about someone else
                    q["outcome"] += "; picture taken out of the scene"
            else:
                pid = identity.confirm_face(q["obs"], a)
                name = next((o["label"] for o in q["options"] if o["value"] == a), a)
                if face:
                    m["faces"].append({"id": pid, "name": name.removeprefix("Yes, "), "bbox": face["bbox"],
                                       "frame": face.get("frame"), "obs": face["obs"], "conf": 1.0, "by": "user"})
                    m["people"] = sorted({f["name"] for f in m["faces"]})
                    m["unknown"] = [f for f in m["unknown"] if f["obs"] != q["obs"]]
                q["outcome"] = f"linked to {name.removeprefix('Yes, ')} in the graph"
        elif q["kind"] == "pick" and sc:
            default = q["default"]
            if a != default and a in ms:
                other = next((s for s in scenes if a in s["moment_ids"]), None)
                if other is not None and other is not sc:   # the chosen picture was used elsewhere: swap
                    other["moment_ids"][other["moment_ids"].index(a)] = default
                if default in sc["moment_ids"]:
                    sc["moment_ids"][sc["moment_ids"].index(default)] = a
                else:
                    sc["moment_ids"].insert(0, a)
                q["outcome"] = "changed to the owner's pick"
            else:
                q["outcome"] = "the owner kept the crew's pick"
        log.append(f"{q['text']} - {q['outcome']}")
    return log
