"""GPU worker for Meta's open-weights audio models. Runs in .venv-gpu (torch + transformers):

    .venv-gpu\\Scripts\\python.exe mlg\\studio\\gpu_worker.py jobs.json

jobs.json: [{"type": "music", "cues": [{"prompt": ..., "seconds": ...}], "out": "x.wav", "seed": 1},
            {"type": "tts", "text": ..., "lang": "eng", "out": "y.wav"}]
Models load once per batch: MusicGen (facebook/musicgen-*) and MMS-TTS (facebook/mms-tts-*),
both CC-BY-NC 4.0 (fine for the hackathon; not for a commercial product).
Writes a result line per job to stdout as JSON.
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import soundfile as sf
import torch

MUSIC_MODEL = os.environ.get("MUSICGEN_MODEL", "facebook/musicgen-small")   # or musicgen-medium
XFADE_S = 3.0
_cache: dict = {}


def _device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def _musicgen():
    if "music" not in _cache:
        from transformers import AutoProcessor, MusicgenForConditionalGeneration
        proc = AutoProcessor.from_pretrained(MUSIC_MODEL)
        model = MusicgenForConditionalGeneration.from_pretrained(
            MUSIC_MODEL, torch_dtype=torch.float16 if _device() == "cuda" else torch.float32).to(_device())
        _cache["music"] = (proc, model)
    return _cache["music"]


def _tts(lang: str):
    key = f"tts-{lang}"
    if key not in _cache:
        from transformers import AutoTokenizer, VitsModel
        name = f"facebook/mms-tts-{lang}"
        _cache[key] = (AutoTokenizer.from_pretrained(name), VitsModel.from_pretrained(name).to(_device()))
    return _cache[key]


def music(job: dict) -> dict:
    """One clip per cue (all cues in one batch), joined with crossfades into a single score."""
    proc, model = _musicgen()
    sr = model.config.audio_encoder.sampling_rate
    cues = job["cues"]
    torch.manual_seed(int(job.get("seed", 0)))
    longest = max(c["seconds"] for c in cues) + XFADE_S
    inputs = proc(text=[c["prompt"] for c in cues], padding=True, return_tensors="pt").to(_device())
    with torch.no_grad():
        out = model.generate(**inputs, do_sample=True, guidance_scale=3.0,
                             max_new_tokens=int(min(longest, 30) * model.config.audio_encoder.frame_rate))
    clips = [out[i, 0].float().cpu().numpy() for i in range(len(cues))]
    x = int(XFADE_S * sr)
    score = np.zeros(0, np.float32)
    for c, clip in zip(cues, clips):
        clip = clip[: int((c["seconds"] + XFADE_S) * sr)]
        if len(score) >= x and len(clip) >= x:
            ramp = np.linspace(0, 1, x, dtype=np.float32)
            head = score[-x:] * (1 - ramp) + clip[:x] * ramp
            score = np.concatenate([score[:-x], head, clip[x:]])
        else:
            score = np.concatenate([score, clip])
    score /= max(1e-6, float(np.abs(score).max())) / 0.9
    sf.write(job["out"], score, sr)
    return {"out": job["out"], "seconds": round(len(score) / sr, 2), "sr": sr}


def tts(job: dict) -> dict:
    tok, model = _tts(job.get("lang", "eng"))
    inputs = tok(job["text"], return_tensors="pt").to(_device())
    model.speaking_rate = float(job.get("rate", 0.95))
    torch.manual_seed(int(job.get("seed", 0)))
    with torch.no_grad():
        wav = model(**inputs).waveform[0].float().cpu().numpy()
    sr = model.config.sampling_rate
    sf.write(job["out"], wav / max(1e-6, float(np.abs(wav).max())) * 0.9, sr)
    return {"out": job["out"], "seconds": round(len(wav) / sr, 2), "sr": sr}


def main() -> None:
    jobs = json.loads(open(sys.argv[1], encoding="utf-8-sig").read())
    for job in jobs:
        t = time.perf_counter()
        try:
            res = music(job) if job["type"] == "music" else tts(job)
            res.update(ok=True, type=job["type"], wall=round(time.perf_counter() - t, 1))
        except Exception as e:  # noqa: BLE001 - report and continue with the next job
            res = {"ok": False, "type": job["type"], "out": job.get("out"), "error": f"{type(e).__name__}: {e}"}
        print(json.dumps(res), flush=True)


if __name__ == "__main__":
    main()
