"""Capability probe: which Meta Model API features actually work for us, how fast, how much.

Makes its own sample media (Muse Image photo, Windows speech WAV, ffmpeg clip),
runs one small request per capability and writes docs/probe_report.md.
Run:  .venv\\Scripts\\python.exe scripts\\probe.py [--skip-image] [--only name,name]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw  # noqa: E402

from mlg.config import CACHE, ROOT, settings  # noqa: E402
from mlg.muse import chat  # noqa: E402
from mlg.muse.chat import Provider  # noqa: E402

SAMPLES = CACHE / "probe_samples"
REPORT = ROOT / "docs" / "probe_report.md"

# $ per 1M tokens (input, output) from dev.meta.ai pricing, 2026-10-26
PRICES = {"muse-spark-1.3": (1.25, 4.25), "muse-spark-1.2": (1.25, 4.25),
          "muse-wonder-1.0": (4.00, 20.00)}

SPEECH = ("Happy birthday Mom! Seventy years old and still the fastest dancer in the family. "
          "Do you remember the trip to the beach in nineteen ninety four? We laughed all day.")

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["summary", "people_count", "emotions"],
    "properties": {
        "summary": {"type": "string"},
        "people_count": {"type": "integer"},
        "emotions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["name", "confidence"],
            "properties": {"name": {"type": "string"}, "confidence": {"type": "number"}}}},
    },
}


def cost(model: str, usage: dict) -> float | None:
    if model not in PRICES or not usage:
        return None
    i = usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0
    o = usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
    pi, po = PRICES[model]
    return round(i / 1e6 * pi + o / 1e6 * po, 5)


def make_samples(use_muse_image: bool) -> dict[str, Path]:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    photo = SAMPLES / "party.png"
    if not photo.exists() and use_muse_image:
        try:
            from mlg.muse.image import generate
            generate("A candid family photo at a backyard 70th birthday party: a grandmother "
                     "blowing out candles on a cake, two adults and two kids laughing around her, "
                     "string lights, late afternoon, shot on a phone", photo, size="1536x1024")
        except Exception as e:  # noqa: BLE001
            print("Muse Image failed, drawing a placeholder:", e)
    if not photo.exists():
        img = Image.new("RGB", (1200, 800), (235, 225, 200))
        d = ImageDraw.Draw(img)
        d.rectangle((450, 450, 750, 650), fill=(250, 240, 245))
        for x in range(480, 740, 50):
            d.rectangle((x, 400, x + 8, 450), fill=(240, 200, 60))
        for cx in (250, 400, 800, 950):
            d.ellipse((cx - 50, 200, cx + 50, 300), fill=(220, 180, 150))
            d.rectangle((cx - 60, 300, cx + 60, 600), fill=(90, 120, 200))
        d.text((420, 700), "HAPPY 70TH BIRTHDAY", fill=(180, 30, 60))
        img.save(photo)

    speech = SAMPLES / "speech.wav"
    if not speech.exists():
        ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              f"$s.SetOutputToWaveFile('{speech}'); $s.Speak(\"{SPEECH}\"); $s.Dispose()")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)

    clip = SAMPLES / "clip.mp4"
    if not clip.exists():
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(photo), "-i", str(speech),
                        "-vf", "scale=1280:-2,zoompan=z='min(zoom+0.0015,1.3)':d=1:s=1280x854:fps=25",
                        "-t", "10", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                        "-shortest", str(clip)], check=True)
    return {"photo": photo, "speech": speech, "clip": clip}


def run(name: str, fn, results: list[dict]) -> None:
    print(f"- {name} ...", flush=True)
    t0 = time.perf_counter()
    row: dict = {"name": name}
    try:
        row.update(fn() or {})
        row["ok"] = True
    except Exception as e:  # noqa: BLE001
        row["ok"] = False
        row["error"] = f"{type(e).__name__}: {e}"[:400]
        traceback.print_exc(limit=1)
    row["wall_s"] = round(time.perf_counter() - t0, 2)
    print(f"  {'OK ' if row['ok'] else 'FAIL'} {row.get('note') or row.get('error', '')}"[:300], flush=True)
    results.append(row)


def ans_row(a: chat.Answer, note: str) -> dict:
    return {"model": a.model, "seconds": a.seconds, "usage": a.usage, "usd": cost(a.model, a.usage),
            "note": note, "cached": a.cached}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-image", action="store_true", help="don't spend on Muse Image")
    ap.add_argument("--only", default="", help="comma list of probe names")
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()
    s = settings()
    s.require_key()
    m = make_samples(not a.skip_image)
    uc = not a.no_cache
    results: list[dict] = []

    def t_text():
        r = chat.ask([chat.text("Reply with exactly: pong")], effort="minimal", max_tokens=2000, use_cache=uc)
        return ans_row(r, r.text.strip()[:80])

    def t_image():
        r = chat.ask([chat.text("Describe who is in this photo, what is happening and the mood, in 3 sentences."),
                      chat.image(m["photo"])], use_cache=uc)
        return ans_row(r, r.text.strip()[:200])

    def t_image_json():
        r = chat.ask([chat.text("Analyse this photo."), chat.image(m["photo"])], schema=SCHEMA, use_cache=uc)
        return ans_row(r, json.dumps(r.data, ensure_ascii=False)[:200])

    def t_audio(model):
        def f():
            r = chat.ask([chat.text("Transcribe this audio, then say the speaker's tone and emotion."),
                          chat.audio(m["speech"])], model=model, max_tokens=4000, use_cache=uc)
            return ans_row(r, r.text.strip()[:200])
        return f

    def t_video(model):
        def f():
            r = chat.ask([chat.text("Watch this clip. What do you see and hear? Give timestamps for "
                                    "the key moments and the emotional tone."), chat.video(m["clip"])],
                         model=model, use_cache=uc)
            return ans_row(r, r.text.strip()[:200])
        return f

    def t_resp_json():
        r = chat.ask([chat.text("Analyse this photo."), chat.image(m["photo"])], schema=SCHEMA,
                     force_responses=True, use_cache=uc)
        return ans_row(r, json.dumps(r.data, ensure_ascii=False)[:200])

    def t_transcribe():
        from mlg.muse.transcribe import transcribe
        tr = transcribe(m["speech"], languages=["English", "Hebrew"], use_cache=uc)
        return {"note": f"{len(tr.turns)} turns: {tr.text[:160]}", "duration_ms": tr.duration_ms}

    def t_sam():
        from mlg.muse.sam import segment
        segs = segment(m["photo"], "person", use_cache=uc)
        raster = segs[0].raster() if segs and segs[0].mask else b""
        return {"note": f"{len(segs)} people; first box {segs[0].box if segs else None}; "
                        f"mask px {sum(raster)}"}

    def t_sam_video():
        from mlg.muse.sam import segment
        segs = segment(m["clip"], "person", use_cache=uc)
        frames = {sg.frame for sg in segs}
        return {"note": f"{len({sg.object_id for sg in segs})} objects over {len(frames)} frames"}

    def t_baseten():
        r = chat.ask([chat.text("In one sentence, what is in this photo?"), chat.image(m["photo"])],
                     provider=Provider.baseten(), use_cache=uc)
        return ans_row(r, r.text.strip()[:200])

    probes = [
        ("spark-1.3 text", t_text),
        ("spark-1.3 image", t_image),
        ("spark-1.3 image + json_schema (chat)", t_image_json),
        ("spark-1.3 image + json_schema (responses)", t_resp_json),
        ("spark-1.2 audio", t_audio(s.audio_model)),
        ("spark-1.3 audio", t_audio(s.model)),
        ("spark-1.3 video (10 s)", t_video(s.model)),
        ("wonder-1.0 video (10 s)", t_video(s.heavy_model)),
        ("voice-transcribe diarization", t_transcribe),
        ("sam-3.1 image", t_sam),
        ("sam-3.1 video", t_sam_video),
    ]
    if s.baseten_key:
        probes.append(("baseten muse-spark-open image", t_baseten))
    only = {x.strip() for x in a.only.split(",") if x.strip()}
    for name, fn in probes:
        if not only or any(o in name for o in only):
            run(name, fn, results)

    (CACHE / "probe.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    lines = ["# Capability probe", "", f"Run {time.strftime('%Y-%m-%d %H:%M')} against `{s.base_url}`.", "",
             "| Probe | OK | Model s | Wall s | Tokens in/out | $ | Note |", "|---|---|---|---|---|---|---|"]
    for r in results:
        u = r.get("usage") or {}
        tok = (f"{u.get('prompt_tokens', u.get('input_tokens', ''))}/"
               f"{u.get('completion_tokens', u.get('output_tokens', ''))}") if u else ""
        note = (r.get("note") or r.get("error") or "").replace("|", "/").replace("\n", " ")
        lines.append(f"| {r['name']} | {'yes' if r['ok'] else '**no**'} | {r.get('seconds', '')} | "
                     f"{r['wall_s']} | {tok} | {r.get('usd') or ''} | {note[:220]} |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nreport: {REPORT}")


if __name__ == "__main__":
    main()
