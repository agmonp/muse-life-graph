"""The Sound crew: a Muse sound designer writes the score brief, Meta's open models perform it.

- Sound designer (Muse Spark): reads the script's arc and the timeline and writes 2-4 music
  cues (instrumentation, tempo, mood, where it lifts or softens) for MusicGen.
- Composer (MusicGen, local GPU): one clip per cue, crossfaded into a score that follows the arc.
- Narrator (MMS-TTS, local GPU): speaks each scene's narration line; the shot is held long enough.
Everything is cached by content, so v2 reuses v1's score and only re-voices changed lines.
If the GPU environment is missing, the film falls back to the synthesized placeholder score.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import soundfile as sf

from mlg.config import CACHE, ROOT
from mlg.muse import chat

GPU_PY = ROOT / ".venv-gpu" / "Scripts" / "python.exe"
WORKER = ROOT / "mlg" / "studio" / "gpu_worker.py"
OUT = CACHE / "sound"
MAX_CUE = 26.0
SCORE_MARGIN = 8.0   # compose a little longer than the cut, so the critic's changes still fit

CUE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["cues", "why"],
    "properties": {
        "why": {"type": "string", "description": "one line for the Edit Room"},
        "cues": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["from_scene", "prompt"],
            "properties": {
                "from_scene": {"type": "integer", "description": "scene order where this cue starts"},
                "prompt": {"type": "string", "description": "MusicGen prompt, <= 30 words"},
            }}},
    },
}
SYSTEM = (
    "You are the SOUND DESIGNER of a short personal film. Write the score as 2-4 music cues that follow the "
    "emotional arc (each cue starts at a scene). Each cue is a MusicGen text prompt: genre, lead "
    "instruments, tempo in bpm, mood and texture, e.g. 'gentle acoustic folk, fingerpicked guitar and soft "
    "piano, 84 bpm, warm and nostalgic, light and airy'. Keep one musical family across cues (same key "
    "feel and instruments) so the crossfades sound intentional; let the peak cue lift. No vocals, no lyrics, "
    "nothing that would fight a spoken voice line.")


def _gpu_ready() -> bool:
    return GPU_PY.exists()


def _run(jobs: list[dict]) -> list[dict]:
    todo = [j for j in jobs if not Path(j["out"]).exists()]
    if todo:
        OUT.mkdir(parents=True, exist_ok=True)
        spec = OUT / f"jobs_{hashlib.sha1(json.dumps(todo).encode()).hexdigest()[:10]}.json"
        spec.write_text(json.dumps(todo), encoding="utf-8")
        r = subprocess.run([str(GPU_PY), str(WORKER), str(spec)], capture_output=True, text=True, timeout=1800)
        for line in r.stdout.splitlines():
            res = json.loads(line)
            if not res.get("ok"):
                raise RuntimeError(f"GPU worker: {res.get('error')}")
        if r.returncode != 0:
            raise RuntimeError(f"GPU worker failed: {r.stderr[-800:]}")
    return [{"out": j["out"], "seconds": sf.info(j["out"]).duration} for j in jobs]


def design(storyboard: dict, edl: dict) -> dict:
    scenes = [{"order": s["order"], "intent": s["intent"], "emotion": s.get("emotion"),
               "has_voice": bool(s.get("voice_line_ids"))} for s in storyboard["script"]["scenes"]]
    starts = {}
    for s in edl["shots"]:
        starts.setdefault(s.get("scene"), s["start"])
    brief = storyboard["brief"]
    ans = chat.ask([chat.text(json.dumps({"tone": brief.get("tone"), "occasion": brief.get("occasion"),
                                         "music_mood": brief.get("music_mood"), "duration_s": edl["duration"],
                                         "scenes": scenes, "scene_start_s": starts}, ensure_ascii=False))],
                   system=SYSTEM, schema=CUE_SCHEMA, schema_name="score", effort="low", max_tokens=4000)
    return ans.data


def _cue_times(cues: list[dict], edl: dict) -> list[dict]:
    starts = {}
    for s in edl["shots"]:
        starts.setdefault(s.get("scene"), s["start"])
    timed = sorted(({"prompt": c["prompt"], "start": starts.get(c["from_scene"], 0.0)} for c in cues),
                   key=lambda c: c["start"])
    timed[0]["start"] = 0.0
    out = []
    for i, c in enumerate(timed):
        end = timed[i + 1]["start"] if i + 1 < len(timed) else edl["duration"] + 2.0
        t = c["start"]
        while end - t > 0.5:   # MusicGen makes at most ~30 s per clip: split long cues
            seg = min(MAX_CUE, end - t)
            out.append({"prompt": c["prompt"], "seconds": round(seg, 2)})
            t += seg
    return out


def score(storyboard: dict, edl: dict, seed: int = 0) -> dict | None:
    """Design + compose the score for this cut; returns {path, cues, why} or None without a GPU env."""
    if not _gpu_ready():
        return None
    last = storyboard.get("score_last")
    if last and last["seconds"] >= edl["duration"] + 1.0:
        return {**last, "reused": True}   # v2: the critic's trims still fit inside v1's score
    plan = storyboard.get("score_plan") or design(storyboard, edl)
    storyboard["score_plan"] = plan
    cues = _cue_times(plan["cues"], {**edl, "duration": edl["duration"] + SCORE_MARGIN})
    key = hashlib.sha1(json.dumps([cues, seed, os.environ.get("MUSICGEN_MODEL", "")]).encode()).hexdigest()[:16]
    out = OUT / f"score_{key}.wav"
    res = _run([{"type": "music", "cues": cues, "out": str(out), "seed": seed}])[0]
    storyboard["score_last"] = {"path": str(out), "cues": cues, "why": plan["why"], "seconds": res["seconds"]}
    return storyboard["score_last"]


def narrate(edl: dict, language: str = "en") -> int:
    """Voice every caption (the scene narration) and make each shot long enough to hold it."""
    if not _gpu_ready():
        return 0
    lang = "heb" if language == "he" else "eng"
    jobs, shots = [], []
    for s in edl["shots"]:
        text = s.get("caption")
        if not text or s["kind"] not in ("still", "clip"):
            s.pop("narration", None)
            continue
        key = hashlib.sha1(f"{lang}|{text}".encode()).hexdigest()[:16]
        out = OUT / f"narr_{key}.wav"
        jobs.append({"type": "tts", "text": text, "lang": lang, "out": str(out)})
        shots.append(s)
    for s, res in zip(shots, _run(jobs)):
        s["narration"] = {"path": res["out"], "dur": round(res["seconds"], 2)}
    return len(shots)
