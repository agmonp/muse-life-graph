"""The Editor: script scenes -> an edit decision list (EDL) of timed shots and sounds.

Deterministic code, no model: the screenwriter decided what each scene shows,
the editor decides how long each picture stays, where the camera drifts (toward
the person the scene is about), where voices start, and which captions appear.
`retime()` recomputes every start after the critic changes durations or drops
shots, so voices stay anchored to their scene and are never cut.
"""
from __future__ import annotations

XFADE = 0.5          # seconds of crossfade between shots
TITLE_S = 3.5
END_S = 3.5
MIN_STILL = 2.6
MAX_STILL = 8.0
MAX_CLIP = 15.0
VOICE_PAD = 0.35


def _bbox_of(moment: dict, person_id: str | None) -> list[int] | None:
    for f in moment.get("faces", []):
        if f.get("bbox") and f["id"] == person_id:
            return f["bbox"]
    return None


def _focus(moment: dict, subject_ids: list[str], prefer: str | None = None) -> list[int] | None:
    """bbox (0-1000 grid) the camera should drift toward: the scene's person, the honoree, else the biggest face."""
    for pid in ([prefer] if prefer else []) + subject_ids:
        if box := _bbox_of(moment, pid):
            return box
    faces = [f for f in moment.get("faces", []) if f.get("bbox")]
    if faces:
        return max(faces, key=lambda f: abs((f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1])))["bbox"]
    return None


def _line_text(u: dict, language: str) -> str:
    """Subtitle text: in an English film the English version (translated, and punctuated -
    raw transcripts have none); in a Hebrew film the original words."""
    if language == "en" and u.get("text_en"):
        return u["text_en"]
    return u.get("text") or ""


def retime(edl: dict) -> dict:
    """Recompute starts; voices start 0.4 s into their scene and the scene stretches to fit them."""
    xf = edl["xfade"]
    shots, voices = edl["shots"], edl["voices"]
    for _ in range(2):  # second pass after stretching
        t, scene_start = 0.0, {}
        for s in shots:
            s["start"] = round(t, 3)
            scene_start.setdefault(s.get("scene"), t)
            t += s["dur"] - xf
        for v in voices:
            v["at"] = round(scene_start.get(v["scene"], 0.0) + 0.4, 2)
        stretched = False
        for v in voices:
            end = v["at"] + (v["t1"] - v["t0"]) + 0.6
            scene_shots = [s for s in shots if s.get("scene") == v["scene"] and s["kind"] != "end"]
            if not scene_shots:
                continue
            last = scene_shots[-1]
            if last["start"] + last["dur"] - xf < end:
                last["dur"] = round(end - last["start"] + xf, 2)
                stretched = True
        if not stretched:
            break
    edl["duration"] = round(t + xf, 2)
    return edl


def build(storyboard: dict) -> dict:
    brief, script, ms = storyboard["brief"], storyboard["script"], storyboard["moments"]
    subjects = brief.get("subject_ids", [])
    lang = brief.get("language", "en")
    checks = storyboard.get("picture_check", {})
    shots: list[dict] = []
    voices: list[dict] = []
    last_visual: dict | None = None
    prev_year = None

    for si, sc in enumerate(sorted(script["scenes"], key=lambda s: s["order"])):
        verdict = checks.get(str(sc["order"]), {})
        focus_of = {v["moment_id"]: v.get("focus_person_id") for v in verdict.get("verdicts", [])}
        visual = [ms[i] for i in sc["moment_ids"] if ms[i]["kind"] in ("photo", "video")]
        audio_only = [ms[i] for i in sc["moment_ids"] if ms[i]["kind"] == "audio"]
        if not visual and last_visual is not None:
            visual = [last_visual]   # a voice recording needs a picture under it
        if not visual:
            continue
        clip_len = sum(min(m["duration"] or 0, MAX_CLIP) for m in visual if m["kind"] == "video")
        n_stills = sum(1 for m in visual if m["kind"] == "photo")
        still_dur = (min(MAX_STILL, max(MIN_STILL, (sc["target_sec"] - clip_len) / n_stills + XFADE))
                     if n_stills else 0)
        for k, m in enumerate(visual):
            year = (m.get("date") or "")[:4] or None
            shot = {"kind": "still" if m["kind"] == "photo" else "clip", "moment": m["id"], "path": m["path"],
                    "focus": _focus(m, subjects, focus_of.get(m["id"])),
                    "caption": sc["narration"] if k == 0 and sc.get("narration") else None,
                    "year": year if year and year != prev_year and k == 0 else None,
                    "scene": sc["order"], "emotion": sc.get("emotion")}
            prev_year = year or prev_year
            if m["kind"] == "photo":
                shot["dur"] = round(still_dur, 2)
            else:
                said = [u for u in m["said"] if u["id"] in sc["voice_line_ids"]]
                t0 = max(0.0, (said[0]["t0"] or 0) - 0.3) if said else 0.0
                shot.update(dur=round(min((m["duration"] or 5) - t0, MAX_CLIP) + XFADE, 2), t0=t0,
                            own_audio=True,
                            subtitle=" ".join(_line_text(u, lang) for u in said) if said else None)
            if si == 0 and k == 0:
                # frame 0 is the title card on the honoree's picture - never black
                shots.append({**shot, "kind": "title", "own_audio": False, "subtitle": None, "caption": None,
                              "year": None, "dur": TITLE_S + (shot["dur"] if shot["kind"] == "still" else 0),
                              "title": script.get("title") or brief.get("title"),
                              "title_sub": script.get("subtitle") or brief.get("subtitle")})
                if shot["kind"] == "clip":
                    shots.append(shot)
            else:
                shots.append(shot)
            last_visual = m
        for m in audio_only:
            for u in m["said"]:
                if u["id"] in sc["voice_line_ids"]:
                    # transcripts give turn-level times only: pad so the first and last words survive
                    voices.append({"path": m["path"], "t0": max(0.0, (u["t0"] or 0) - VOICE_PAD),
                                   "t1": min(m["duration"] or 1e9, (u["t1"] or (m["duration"] or 0)) + VOICE_PAD),
                                   "scene": sc["order"], "text": _line_text(u, lang), "speaker": u.get("speaker")})
    if shots:
        last = shots[-1]
        shots.append({"kind": "end", "moment": last["moment"], "path": last["path"], "focus": last.get("focus"),
                      "dur": END_S, "text": script.get("closing_card") or "", "scene": last["scene"]})
    return retime({"shots": shots, "voices": voices, "xfade": XFADE,
                   "aspect": brief.get("aspect", "16:9"), "music_mood": brief.get("music_mood", "warm"),
                   "language": brief.get("language", "en")})
