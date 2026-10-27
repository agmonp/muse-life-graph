"""Producer + Screenwriter: one sentence -> a brief -> a scene-by-scene script.

Each crew member's reasoning is kept in the storyboard ("crew_log") so the Edit
Room can show who decided what, and why.
"""
from __future__ import annotations

import json
import time

from mlg.config import ROOT, settings
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


def plan(request: str, dataset: str = "demo", template: str | None = None) -> dict:
    t0 = time.perf_counter()
    ms = research.moments(dataset)
    brief = produce(request, dataset, ms)
    brief["template"] = templates.pick(brief["occasion"], template)
    t1 = time.perf_counter()
    script = write_script(brief, ms)
    t2 = time.perf_counter()
    notes = validate(script, ms) + templates.check(brief["template"], script)
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
