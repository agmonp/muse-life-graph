"""The Editor: script scenes -> an edit decision list (EDL) of timed shots and sounds.

Deterministic code, no model: the screenwriter decided what each scene shows,
the editor decides how long each picture stays, where the camera drifts (toward
the honoree's face), where voices start, and which captions appear.
"""
from __future__ import annotations

XFADE = 0.5          # seconds of crossfade between shots
TITLE_S = 3.5
END_S = 3.5
MIN_STILL = 2.6
MAX_CLIP = 15.0


def _focus(moment: dict, subject_ids: list[str]) -> list[int] | None:
    """bbox (0-1000 grid) the camera should drift toward: the honoree, else the biggest face."""
    faces = [f for f in moment.get("faces", []) if f.get("bbox")]
    for sid in subject_ids:
        for f in faces:
            if f["id"] == sid:
                return f["bbox"]
    if faces:
        return max(faces, key=lambda f: abs((f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1])))["bbox"]
    return None


def _year(moment: dict) -> str | None:
    return (moment.get("date") or "")[:4] or None


def build(storyboard: dict) -> dict:
    brief, script, ms = storyboard["brief"], storyboard["script"], storyboard["moments"]
    subjects = brief.get("subject_ids", [])
    lines = {u["id"]: (m, u) for m in ms.values() for u in m["said"]}
    shots: list[dict] = []
    voices: list[dict] = []
    t = 0.0
    last_visual: dict | None = None
    prev_year = None

    def add(shot: dict) -> dict:
        nonlocal t
        shot["start"] = round(t, 3)
        shots.append(shot)
        t += shot["dur"] - XFADE
        return shot

    scenes = sorted(script["scenes"], key=lambda s: s["order"])
    for si, sc in enumerate(scenes):
        visual = [ms[i] for i in sc["moment_ids"] if ms[i]["kind"] in ("photo", "video")]
        audio_only = [ms[i] for i in sc["moment_ids"] if ms[i]["kind"] == "audio"]
        if not visual and last_visual is not None:
            visual = [last_visual]   # a voice recording needs a picture under it
        if not visual:
            continue
        scene_start = t
        clip_len = sum(min(m["duration"] or 0, MAX_CLIP) for m in visual if m["kind"] == "video")
        n_stills = sum(1 for m in visual if m["kind"] == "photo")
        still_dur = max(MIN_STILL, (sc["target_sec"] - clip_len) / n_stills + XFADE) if n_stills else 0
        for k, m in enumerate(visual):
            year = _year(m)
            caption = sc["narration"] if k == 0 and sc.get("narration") else None
            shot = {"kind": "still" if m["kind"] == "photo" else "clip", "moment": m["id"], "path": m["path"],
                    "focus": _focus(m, subjects), "caption": caption,
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
                            subtitle=" ".join(u["text"] for u in said) if said else None)
            if si == 0 and k == 0:
                # frame 0 is the title card on the honoree's picture - never black
                add({**shot, "kind": "title", "own_audio": False, "subtitle": None, "caption": None, "year": None,
                     "dur": TITLE_S + (shot["dur"] if shot["kind"] == "still" else 0),
                     "title": script.get("title") or brief.get("title"),
                     "title_sub": script.get("subtitle") or brief.get("subtitle")})
                if shot["kind"] == "clip":
                    add(shot)
                last_visual = m
                continue
            add(shot)
            last_visual = m
        last_visual = visual[-1]
        # voice lines from recordings play over the scene's pictures
        for m in audio_only:
            for u in m["said"]:
                if u["id"] in sc["voice_line_ids"]:
                    voices.append({"path": m["path"], "t0": u["t0"] or 0, "t1": u["t1"] or (m["duration"] or 0),
                                   "at": round(scene_start + 0.4, 2), "text": u["text"], "speaker": u.get("speaker")})
        # stretch the scene's last shot if a voice line runs past it
        for v in voices:
            end = v["at"] + (v["t1"] - v["t0"]) + 0.6
            if v["at"] >= scene_start and end > t + XFADE:
                extra = end - (t + XFADE)
                shots[-1]["dur"] = round(shots[-1]["dur"] + extra, 2)
                t += extra

    if shots:
        last = shots[-1]
        add({"kind": "end", "moment": last["moment"], "path": last["path"], "focus": last.get("focus"),
             "dur": END_S, "text": script.get("closing_card") or "", "scene": last["scene"]})
    total = round(t + XFADE, 2)
    return {"shots": shots, "voices": voices, "duration": total, "xfade": XFADE,
            "aspect": brief.get("aspect", "16:9"), "music_mood": brief.get("music_mood", "warm"),
            "language": brief.get("language", "en")}
