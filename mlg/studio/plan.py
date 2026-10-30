"""Producer + Screenwriter: one sentence -> a brief -> a scene-by-scene script.

Each crew member's reasoning is kept in the storyboard ("crew_log") so the Edit
Room can show who decided what, and why.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from mlg.config import ROOT, settings
from mlg.ingest import phash
from mlg.muse import chat
from mlg.people import roster
from mlg.studio import research, templates

PROMPTS = ROOT / "mlg" / "prompts"

BRIEF_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["subject_ids", "occasion", "tone", "target_seconds", "aspect", "title", "subtitle",
                 "language", "music_mood", "must_include", "avoid", "notes"],
    "properties": {
        "subject_ids": {"type": "array", "items": {"type": "string"}},
        "occasion": {"type": "string"},
        "tone": {"type": "string"},
        "target_seconds": {"type": "integer"},
        "aspect": {"type": "string", "enum": ["16:9", "9:16"]},
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "language": {"type": "string", "enum": ["en", "he"]},
        "music_mood": {"type": "string", "enum": ["warm", "joyful", "tender", "playful", "epic"]},
        "must_include": {"type": "array", "items": {"type": "string"}},
        "avoid": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
}

SCRIPT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["title", "subtitle", "logline", "arc", "scenes", "closing_card", "doubts"],
    "properties": {
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "logline": {"type": "string"},
        "arc": {"type": "array", "items": {"type": "string"}},
        "scenes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["order", "beat", "intent", "moment_ids", "narration", "voice_line_ids", "target_sec",
                         "emotion"],
            "properties": {
                "order": {"type": "integer"},
                "beat": {"type": "string", "description": "the template beat this scene belongs to"},
                "intent": {"type": "string", "description": "what this scene does in the story"},
                "moment_ids": {"type": "array", "items": {"type": "string"}},
                "narration": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "voice_line_ids": {"type": "array", "items": {"type": "string"}},
                "target_sec": {"type": "number"},
                "emotion": {"type": "string"},
            }}},
        "closing_card": {"type": "string", "description": "one short line for the last frame"},
        "doubts": {"type": "array", "description": "at most 1-2 picture choices only the owner can settle",
                   "items": {
                       "type": "object", "additionalProperties": False,
                       "required": ["scene_order", "question", "options", "chosen_moment_id", "why"],
                       "properties": {
                           "scene_order": {"type": "integer"},
                           "question": {"type": "string", "description": "short, in the brief's language"},
                           "options": {"type": "array", "items": {
                               "type": "object", "additionalProperties": False,
                               "required": ["moment_id", "label"],
                               "properties": {"moment_id": {"type": "string"}, "label": {"type": "string"}}}},
                           "chosen_moment_id": {"type": "string", "description": "the one you put in the scene"},
                           "why": {"type": "string"},
                       }}},
    },
}


def produce(request: str, dataset: str, ms: list[dict]) -> dict:
    people = roster(dataset)
    kinds = [m["kind"] for m in ms]
    dates = sorted(m["date"][:4] for m in ms if m.get("date"))
    system = (PROMPTS / "producer.md").read_text(encoding="utf-8").format(
        people=json.dumps([{"id": p["id"], "name": p["name"], "relation": p.get("relation")} for p in people],
                          ensure_ascii=False),
        n_moments=len(ms), n_photos=kinds.count("photo"), n_videos=kinds.count("video"),
        n_audio=kinds.count("audio"), span=f"{dates[0]}-{dates[-1]}" if dates else "unknown years")
    ans = chat.ask([chat.text(f"REQUEST: {request}")], system=system, schema=BRIEF_SCHEMA,
                   schema_name="brief", effort="low")
    return ans.data


def write_script(brief: dict, ms: list[dict]) -> dict:
    system = (PROMPTS / "screenwriter.md").read_text(encoding="utf-8").format(
        brief=json.dumps(brief, ensure_ascii=False),
        template=templates.for_prompt(brief["template"], brief["target_seconds"]),
        moments=json.dumps(research.for_prompt(ms), ensure_ascii=False))
    for attempt in range(3):
        ans = chat.ask([chat.text("Write the film now.")], system=system, model=settings().heavy_model,
                       schema=SCRIPT_SCHEMA, schema_name="script", effort="high", max_tokens=24000,
                       use_cache=attempt == 0)
        if not hollow(ans.data):
            break
    return repair(ans.data, {m["id"]: m for m in ms}, brief)


def hollow(script: dict) -> bool:
    """Wonder sometimes returns the right scenes with every free-text field blank and all lengths 0."""
    scenes = script.get("scenes") or []
    return not scenes or not script.get("logline") or \
        sum(1 for s in scenes if not s.get("intent") or not s.get("target_sec")) > len(scenes) / 2


def repair(script: dict, known: dict, brief: dict) -> dict:
    """Fill what is still blank after the retries, so a hollow reply still makes a sane film."""
    t = templates.TEMPLATES[brief["template"]]
    for s in script["scenes"]:
        if not s.get("target_sec"):
            s["target_sec"] = round(sum(min(known[m]["duration"] or 5, 15) if known[m]["kind"] == "video"
                                        else t["sec_per_photo"] if known[m]["kind"] == "photo" else 0
                                        for m in s["moment_ids"] if m in known), 1) or t["sec_per_photo"]
        if not s.get("intent"):
            s["intent"] = (s.get("beat") or "scene").replace("_", " ")
    script["arc"] = script.get("arc") or [s.get("beat") or "" for s in script["scenes"]]
    script["logline"] = script.get("logline") or brief.get("subtitle") or brief.get("title") or ""
    script["closing_card"] = script.get("closing_card") or brief.get("title") or ""
    return script


def validate(script: dict, ms: list[dict]) -> list[str]:
    """Code checks on the screenwriter's output; problems are fixed here, not trusted."""
    known = {m["id"]: m for m in ms}
    lines = {u["id"]: u for m in ms for u in m["said"]}
    used, notes = set(), []
    for sc in script["scenes"]:
        keep = []
        for mid in sc["moment_ids"]:
            if mid not in known:
                notes.append(f"scene {sc['order']}: unknown moment {mid[:16]}… dropped")
            elif mid in used:
                notes.append(f"scene {sc['order']}: moment reused - dropped")
            else:
                keep.append(mid)
                used.add(mid)
        sc["moment_ids"] = keep
        sc["voice_line_ids"] = [v for v in sc["voice_line_ids"] if v in lines]
        for v in sc["voice_line_ids"]:
            need = (lines[v]["t1"] or 0) - (lines[v]["t0"] or 0) + 0.8
            if sc["target_sec"] < need:
                notes.append(f"scene {sc['order']}: lengthened to fit the voice line ({need:.1f} s)")
                sc["target_sec"] = round(need, 1)
    script["scenes"] = [sc for sc in script["scenes"] if sc["moment_ids"]]
    return notes


PICK_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["picks"],
    "properties": {"picks": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["scene_order", "moment_ids", "why"],
        "properties": {"scene_order": {"type": "integer"},
                       "moment_ids": {"type": "array", "items": {"type": "string"}},
                       "why": {"type": "string"}}}}},
}
SEC_PER_BLESSING_PHOTO = 8.0   # a long blessing gets a new photo about every 8 s (max 3), never one held still


def _words(text: str) -> set[str]:
    return {w for w in "".join(c.lower() if c.isalnum() else " " for c in text or "").split() if len(w) > 3}


def _overlap_choose(gaps: list[dict], free: list[dict]) -> dict[int, list[str]]:
    """Fallback without a model: the free photos whose descriptions share the most words with the blessing."""
    picks, taken = {}, set()
    for g in gaps:
        words = _words(g["words"])
        ranked = sorted((m for m in free if m["id"] not in taken),
                        key=lambda m: -len(words & _words(f"{m['summary']} {m['event']} {' '.join(m['objects'])}")))
        # keep the chosen photos in date order so the blessing walks forward through time
        chosen = sorted(ranked[:g["photos"]], key=lambda m: m["date"] or "")
        if chosen:
            picks[g["order"]] = [m["id"] for m in chosen]
            taken.update(picks[g["order"]])
    return picks


def _muse_choose(gaps: list[dict], free: list[dict]) -> dict[int, list[str]]:
    """Muse Spark reads each blessing and picks the honoree photos that fit its words."""
    ans = chat.ask([chat.text(json.dumps({
        "blessings": gaps,
        "photos": [{"id": m["id"], "date": (m["date"] or "")[:10], "summary": m["summary"], "event": m["event"],
                    "people": m["people"]} for m in free]}, ensure_ascii=False))],
        system="You are the PICTURE EDITOR of a personal film. Each blessing below plays as a voice over photos of "
               "the person it is for. For every blessing pick exactly `photos` photos whose content fits its words "
               "(a memory it mentions, a time of life, a feeling), in the order they should appear. Use each photo "
               "at most once in all picks. Only ids from the list.",
        schema=PICK_SCHEMA, schema_name="blessing_pictures", effort="low")
    ids, want = {m["id"] for m in free}, {g["order"]: g["photos"] for g in gaps}
    picks, taken = {}, set()
    for p in ans.data.get("picks", []):
        good = [mid for mid in dict.fromkeys(p.get("moment_ids") or []) if mid in ids and mid not in taken]
        good = good[:want.get(p.get("scene_order"), 0)]
        if good:
            picks[p["scene_order"]] = good
            taken.update(good)
    return picks


def _looks(m: dict) -> list[int]:
    if "_looks" not in m:
        try:
            path = Path(m["path"])
            m["_looks"] = [phash.photo_hash(path)] if m["kind"] == "photo" else phash.video_hash(path)[0]
        except Exception:  # noqa: BLE001 - an unreadable file just never counts as a duplicate
            m["_looks"] = []
    return m["_looks"]


def _looks_same(a: dict, b: dict, max_dist: int = phash.PHOTO_MAX_DIST) -> bool:
    """Perceptual, not byte equality: any frame of one within pHash distance of any frame of the other."""
    return any(bin(x ^ y).count("1") <= max_dist for x in _looks(a) for y in _looks(b))


FILM_DUP_DIST = 12   # in a film, two shots of the same instant (a burst, a selfie taken twice) are one too many


def drop_near_duplicates(script: dict, ms: list[dict]) -> list[str]:
    """Keep the first of near-identical pictures in a film; a scene never loses its last picture."""
    known = {m["id"]: m for m in ms}
    kept, notes = [], []
    for sc in sorted(script["scenes"], key=lambda s: s["order"]):
        for mid in list(sc["moment_ids"]):
            m = known.get(mid)
            if not m or m["kind"] not in ("photo", "video"):
                continue
            twin = next((k for k in kept if _looks_same(m, known[k], FILM_DUP_DIST)), None)
            pictures = [x for x in sc["moment_ids"] if known.get(x, {}).get("kind") in ("photo", "video")]
            if twin and len(pictures) > 1:
                sc["moment_ids"].remove(mid)
                notes.append(f"scene {sc['order']}: a near-copy of an earlier picture taken out")
            else:
                kept.append(mid)
    return notes


def picture_blessings(script: dict, ms: list[dict], subject_ids: list[str], choose=None,
                      looks_same=None) -> list[str]:
    """A blessing scene with no picture of its own gets unused photos of the honoree that fit its words,
    instead of the editor holding the previous still for the length of the recording."""
    known = {m["id"]: m for m in ms}
    lines = {u["id"]: u for m in ms for u in m["said"]}
    same = looks_same or _looks_same
    used = {mid for sc in script["scenes"] for mid in sc["moment_ids"]}
    pictures = [mid for mid in used if mid in known and known[mid]["kind"] in ("photo", "video")]
    gaps, notes = [], []
    for sc in script["scenes"]:
        if not any(mid in known and known[mid]["kind"] == "audio" for mid in sc["moment_ids"]):
            continue
        # a picture that looks the same as one elsewhere in the film (the demo's toast video is its photo,
        # a WhatsApp re-send, a burst) is no picture of its own: the viewer sees one image for both scenes
        for mid in [m for m in sc["moment_ids"] if m in pictures]:
            if any(same(known[mid], known[o]) for o in pictures if o != mid and o not in sc["moment_ids"]):
                sc["moment_ids"].remove(mid)
                pictures.remove(mid)
                notes.append(f"scene {sc['order']}: blessing picture looks the same as another shot - replaced")
        kinds = {known[mid]["kind"] for mid in sc["moment_ids"] if mid in known}
        if not kinds & {"photo", "video"}:
            said = [lines[v] for v in sc["voice_line_ids"] if v in lines]
            secs = sum((u["t1"] or 0) - (u["t0"] or 0) for u in said) or sc["target_sec"]
            gaps.append({"order": sc["order"], "photos": max(1, min(3, round(secs / SEC_PER_BLESSING_PHOTO))),
                         "words": " ".join(u.get("text_en") or u["text"] for u in said) or sc.get("intent") or ""})
    if not gaps:
        return notes
    subjects = set(subject_ids)
    free = [m for m in ms if m["kind"] == "photo" and m["id"] not in used
            and {f["id"] for f in m["faces"]} & subjects
            and not any(same(m, known[o]) for o in pictures)]
    picks: dict[int, list[str]] = {}
    if not free:
        pass
    elif choose is None:
        try:
            picks = _muse_choose(gaps, free)
        except Exception as e:  # noqa: BLE001 - a picture choice must never stop the film
            print("blessing pictures: Muse pick failed, using word match:", e)
    else:
        picks = choose(gaps, free)
    missing = [g for g in gaps if g["order"] not in picks]
    if missing and free:
        taken = {mid for v in picks.values() for mid in v}
        picks.update(_overlap_choose(missing, [m for m in free if m["id"] not in taken]))
    for sc in script["scenes"]:
        if mids := picks.get(sc["order"]):
            sc["moment_ids"] = mids + sc["moment_ids"]
            notes.append(f"scene {sc['order']}: blessing now plays over {len(mids)} photo(s) of its own ("
                         + "; ".join(f"{(known[m]['date'] or '')[:4]} {(known[m]['summary'] or '')[:40]}"
                                     for m in mids) + ")")

    for g in gaps:
        if g["order"] not in picks:
            notes.append(_join_neighbour(script, known, g["order"]))
    return notes


def _join_neighbour(script: dict, known: dict, order: int) -> str:
    """No spare photo of the honoree: the blessing joins the nearest scene with the most photos and no voice of
    its own, so it plays over pictures that change rather than one still held for the whole recording."""
    scenes = sorted(script["scenes"], key=lambda s: s["order"])
    k = next(i for i, s in enumerate(scenes) if s["order"] == order)
    sc = scenes[k]

    def photos(s):
        return sum(1 for m in s["moment_ids"] if m in known and known[m]["kind"] == "photo")

    hosts = [s for s in scenes if s is not sc and photos(s) and not s["voice_line_ids"]
             and not any(known[m]["kind"] == "video" for m in s["moment_ids"] if m in known)]
    if not hosts:
        return f"scene {order}: blessing has no picture and no scene to share"
    host = min(hosts, key=lambda s: (-min(photos(s), 3), abs(scenes.index(s) - k), scenes.index(s) > k))
    host["moment_ids"] += sc["moment_ids"]
    host["voice_line_ids"] += sc["voice_line_ids"]
    host["target_sec"] = max(host["target_sec"], sc["target_sec"])
    host["narration"] = None   # never narrate over a voice line
    script["scenes"].remove(sc)
    return f"scene {order}: no spare photo of the honoree - blessing moved over scene {host['order']}'s photos"


def plan(request: str, dataset: str = "real", template: str | None = None) -> dict:
    t0 = time.perf_counter()
    ms = research.moments(dataset)
    brief = produce(request, dataset, ms)
    brief["template"] = templates.pick(brief["occasion"], template)
    t1 = time.perf_counter()
    script = write_script(brief, ms)
    t2 = time.perf_counter()
    notes = (validate(script, ms) + drop_near_duplicates(script, ms)
             + picture_blessings(script, ms, brief.get("subject_ids", []))
             + templates.check(brief["template"], script))
    return {"request": request, "dataset": dataset, "brief": brief, "script": script,
            "moments": {m["id"]: m for m in ms},
            "crew_log": [
                {"who": "Researcher", "did": f"found {len(ms)} moments in the life graph"},
                {"who": "Producer", "did": f"{brief['occasion']} ({templates.TEMPLATES[brief['template']]['label']} "
                                           f"template), {brief['tone']}, {brief['target_seconds']} s, "
                                           f"{brief['aspect']}", "why": brief.get("notes", ""),
                 "seconds": round(t1 - t0, 1)},
                {"who": "Screenwriter", "did": f"{len(script['scenes'])} scenes: {' -> '.join(script['arc'])}",
                 "why": script["logline"], "seconds": round(t2 - t1, 1)},
                {"who": "Script check", "did": f"{len(notes)} fixes", "why": "; ".join(notes)},
            ]}
