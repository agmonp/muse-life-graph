"""The Picture Checker: Muse looks at each scene's actual pictures before anything is cut.

The screenwriter worked from text summaries; here every picture is shown with the
scene's purpose and narration. Pictures that don't fit are dropped (with the
reason, for the Edit Room), the camera's target is set to the person the scene
is about, and narration that the pictures contradict is rewritten.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mlg.muse import chat
from mlg.perceive.keyframes import keyframes

SYSTEM = (
    "You are the PICTURE CHECKER of a personal film. For one scene you get its purpose, its narration "
    "line and its pictures (each labelled with a moment id and who the archive says is in it). Judge "
    "every picture against the scene: does it show what the scene and narration say? Reject a picture "
    "only for a concrete reason (wrong people or event for this scene, the person is not visible, "
    "blurred or eyes closed on the key face, a near-duplicate of another picture in the scene). For "
    "each kept picture name the person the camera should frame (an id from its people list) - the one "
    "the narration is about. If the narration states something the pictures contradict or don't show, "
    "rewrite it (same language, at most 14 words, concrete, no invented facts); otherwise keep it.")

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["verdicts", "narration_ok", "narration_fix", "note"],
    "properties": {
        "verdicts": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["moment_id", "keep", "reason", "focus_person_id"],
            "properties": {
                "moment_id": {"type": "string"},
                "keep": {"type": "boolean"},
                "reason": {"type": "string"},
                "focus_person_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            }}},
        "narration_ok": {"type": "boolean"},
        "narration_fix": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "note": {"type": "string", "description": "one line for the Edit Room"},
    },
}


def _picture(m: dict) -> Path | None:
    if m["kind"] == "photo":
        return Path(m["path"])
    if m["kind"] == "video":
        frames = keyframes(Path(m["path"]))
        return frames[len(frames) // 2][1] if frames else None
    return None


def check_scene(sc: dict, ms: dict) -> dict:
    parts = [chat.text(f"SCENE {sc['order']} - purpose: {sc['intent']}\nNARRATION: {sc.get('narration') or '(none)'}")]
    shown = []
    for mid in sc["moment_ids"]:
        m = ms[mid]
        pic = _picture(m)
        if pic is None:
            continue
        people = [f"{f['id']} ({f['name']})" for f in m.get("faces", [])]
        parts += [chat.text(f"moment_id={mid} | {m['kind']} | {(m.get('date') or '')[:10]} | {m.get('summary')}"
                            f" | people: {', '.join(people) or 'none identified'}"), chat.image(pic)]
        shown.append(mid)
    if not shown:
        return {"verdicts": [], "narration_ok": True, "narration_fix": None, "note": "no pictures to check"}
    ans = chat.ask(parts, system=SYSTEM, schema=SCHEMA, schema_name="picture_check", effort="medium",
                   max_tokens=8000)
    return ans.data


def check(storyboard: dict) -> list[str]:
    """Runs the check on every scene, applies it to the script, returns notes for the crew log."""
    ms = storyboard["moments"]
    scenes = storyboard["script"]["scenes"]
    with ThreadPoolExecutor(6) as ex:
        results = list(ex.map(lambda sc: check_scene(sc, ms), scenes))
    storyboard["picture_check"] = {}
    notes = []
    for sc, res in zip(scenes, results):
        storyboard["picture_check"][str(sc["order"])] = res
        visual = [m for m in sc["moment_ids"] if ms[m]["kind"] in ("photo", "video")]
        dropped = [v for v in res["verdicts"] if not v["keep"] and v["moment_id"] in visual]
        # never empty a scene completely: if every picture failed, keep the least bad (first) one
        if dropped and len(dropped) == len(visual):
            dropped = dropped[1:]
        for v in dropped:
            sc["moment_ids"].remove(v["moment_id"])
            notes.append(f"scene {sc['order']}: dropped a picture - {v['reason']}")
        if not res["narration_ok"] and res.get("narration_fix") and sc.get("narration"):
            notes.append(f"scene {sc['order']}: narration '{sc['narration']}' -> '{res['narration_fix']}'")
            sc["narration_before_check"] = sc["narration"]
            sc["narration"] = res["narration_fix"]
    return notes
