"""The Critic: Muse Wonder watches the rendered draft and gives timestamped notes.

The probe showed video input carries the pictures but not the sound, so the
critic also gets the timeline as text (shot times, captions, the words spoken
and when). Each note maps to one edit operation the code can apply safely;
the same critic then scores the revised cut, so the Edit Room can show
"v1 6/10 -> v2 8/10" with the reasons.
"""
from __future__ import annotations

import json
from pathlib import Path

from mlg.config import settings
from mlg.muse import chat
from mlg.studio.edit import MAX_STILL, MIN_STILL, retime

SYSTEM = (
    "You are the CRITIC of a short personal film (a birthday/family/wedding film made from someone's own "
    "photos and videos). You watch the draft and read its timeline. You cannot hear the audio, so the "
    "timeline tells you what is said and when. Judge it like a demanding film editor who loves the family: "
    "pacing (photos that linger or rush), repetition (two near-identical pictures), the emotional arc (is the "
    "peak in the right place, does it end on a warm, complete note), captions that are wrong, clumsy or "
    "redundant with the picture, a voice line covered by busy cuts, faces cut off by the frame, a weak first "
    "or last shot. A caption marked as spoken by the narrator is the film's narration: judge whether the "
    "line is good, don't remove it just for describing the picture. "
    "Be specific and give at most 6 notes, most important first. Each note must name one "
    "shot index and one operation:\n"
    "  shorten / lengthen (set `seconds` = how many seconds to remove/add), drop (remove the shot), "
    "caption (set `new_caption`; null removes the caption), move_earlier / move_later (swap with the "
    "neighbouring shot), none.\n"
    "`t` is the time in seconds where the problem is (from the timeline). Never drop or move shot 0 "
    "(title) or the last shot (closing card). Score the cut 1-10 honestly.")

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["score", "summary", "notes"],
    "properties": {
        "score": {"type": "integer"},
        "summary": {"type": "string"},
        "notes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["t", "shot", "problem", "op", "seconds", "new_caption", "why"],
            "properties": {
                "t": {"type": "number", "description": "seconds into the film"},
                "shot": {"type": "integer"},
                "problem": {"type": "string"},
                "op": {"type": "string", "enum": ["shorten", "lengthen", "drop", "caption", "move_earlier",
                                                  "move_later", "none"]},
                "seconds": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                "new_caption": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "why": {"type": "string"},
            }}},
    },
}


def timeline(edl: dict) -> str:
    rows = []
    for i, s in enumerate(edl["shots"]):
        bits = [f"shot {i}", f"{s['start']:.1f}-{s['start'] + s['dur']:.1f}s", s["kind"], f"scene {s.get('scene')}"]
        for k in ("title", "caption", "year", "text"):
            if s.get(k):
                spoken = " (also spoken aloud by the narrator)" if k == "caption" and s.get("narration") else ""
                bits.append(f"{k}{spoken}: {s[k]}")
        if s.get("subtitle"):
            bits.append(f"speech in clip: \"{s['subtitle'][:160]}\"")
        rows.append(" | ".join(str(b) for b in bits))
    for v in edl["voices"]:
        rows.append(f"voice {v['at']:.1f}-{v['at'] + v['t1'] - v['t0']:.1f}s ({v.get('speaker') or 'unknown'}): "
                    f"\"{v['text'][:200]}\"")
    return "\n".join(rows)


def watch(video: Path, edl: dict, brief: dict) -> dict:
    parts = [chat.text(f"BRIEF: {json.dumps(brief, ensure_ascii=False)}\nTIMELINE:\n{timeline(edl)}\n\nTHE DRAFT:"),
             chat.video(video)]
    return chat.ask(parts, system=SYSTEM, model=settings().heavy_model, schema=SCHEMA, schema_name="critique",
                    effort="high", max_tokens=16000).data


def apply(edl: dict, critique: dict) -> tuple[dict, list[str]]:
    """Apply the notes that are safe to apply; report each decision for the Edit Room."""
    shots = edl["shots"]
    last = len(shots) - 1
    done, removed = [], set()
    for n in critique["notes"]:
        i, op = n["shot"], n["op"]
        if op == "none" or not 0 <= i <= last:
            continue
        s = shots[i]
        tag = f"{n['t']:.0f}s shot {i}: {op}"
        if i in removed:
            continue
        if op in ("shorten", "lengthen") and s["kind"] in ("still", "title", "end"):
            delta = abs(float(n.get("seconds") or 1.0))
            new = s["dur"] + (delta if op == "lengthen" else -delta)
            floor = MIN_STILL + (3.0 if s["kind"] == "title" else 0)
            s["dur"] = round(min(max(new, floor), MAX_STILL + (3.5 if s["kind"] == "title" else 0)), 2)
            done.append(f"{tag} -> {s['dur']}s ({n['why']})")
        elif op == "drop" and 0 < i < last and s["kind"] == "still":
            scene_left = [x for j, x in enumerate(shots) if x.get("scene") == s.get("scene") and j != i
                          and j not in removed and x["kind"] != "end"]
            voiced = any(v["scene"] == s.get("scene") for v in edl["voices"])
            if scene_left or not voiced:   # a voice line always keeps a picture under it
                removed.add(i)
                done.append(f"{tag} ({n['why']})")
        elif op == "caption" and s["kind"] in ("still", "clip"):
            s["caption"] = (n.get("new_caption") or "").strip() or None
            done.append(f"{tag} -> {s['caption']!r} ({n['why']})")
        elif op in ("move_earlier", "move_later") and 0 < i < last:
            j = i - 1 if op == "move_earlier" else i + 1
            if 0 < j < last and {shots[j]["kind"], s["kind"]} <= {"still", "clip"}:
                shots[i], shots[j] = shots[j], shots[i]
                shots[i]["scene"], shots[j]["scene"] = shots[j]["scene"], shots[i]["scene"]
                done.append(f"{tag} ({n['why']})")
    edl["shots"] = [s for k, s in enumerate(shots) if k not in removed]
    return retime(edl), done
