"""Synthetic demo family (fictional, generated with Muse Image) for development and the public demo.

The Cohen family: grandma Ruth (70), her son David (glasses), his wife Maya
(ponytail), their kids Noam (boy, ~10) and Lia (girl, ~8). Every photo is
generated from the reference party photo so the faces stay consistent.
Output goes to data/demo/ (gitignored); file names carry the dates the way
phones do, the old "scan" has no date so the perceive pass must date it.

    .venv\\Scripts\\python.exe scripts\\make_demo_set.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from mlg.config import CACHE, DATA  # noqa: E402
from mlg.muse.image import generate  # noqa: E402

OUT = DATA / "demo"
REF = CACHE / "probe_samples" / "party.png"
FAMILY = ("the same family as in the reference photo: grandmother Ruth (grey curly hair, round glasses), "
          "her son David (dark hair, beard, rectangular glasses), his wife Maya (brown hair in a ponytail), "
          "their son Noam (curly brown hair) and daughter Lia (blond braid)")

SHOTS = {
    "IMG_20251012_181530.png": f"Candid phone photo, {FAMILY}, grandmother Ruth's 70th birthday in the "
                               "backyard: Ruth dancing joyfully with Lia while the others clap and laugh, string lights.",
    "IMG_20251012_190210.png": f"Candid phone photo, {FAMILY}: David giving an emotional toast to his mother Ruth "
                               "at the backyard table, Ruth wiping a happy tear, Maya holding her hand.",
    "IMG_20250621_103000.png": f"Candid phone photo, {FAMILY}: Ruth teaching Noam to bake challah in her small "
                               "kitchen, flour everywhere, both laughing.",
    "IMG_20250815_171245.png": f"Candid phone photo, {FAMILY}: the four of David, Maya, Noam and Lia hiking on a "
                               "rocky trail with the sea in the distance, Lia on David's shoulders.",
    "IMG_20240203_160000.png": f"Candid phone photo, {FAMILY}: Lia's 7th birthday party in the living room, "
                               "Lia blowing candles on a pink cake, Noam pulling a silly face, Ruth smiling.",
    "IMG_20120905_201500.png": "Wedding photo, 2012: a younger David (beard, glasses, dark suit) and Maya "
                               "(white dress, hair up) dancing their first dance, a younger Ruth (grey-brown "
                               "curly hair) watching from the side with her hands on her heart.",
    "scan_0007.jpg": "Scanned 1990s film print with faded colours, slight grain and a white border: a young "
                     "woman with curly dark-brown hair and round glasses (Ruth in her forties) on a beach, "
                     "holding a laughing curly-haired boy of about six (David) on her hip.",
}


def make(name: str, prompt: str) -> str:
    out = OUT / name
    if out.exists():
        return f"skip {name}"
    tmp = generate(prompt, out.with_suffix(".png"), references=[REF], size="1536x1024")
    if out.suffix == ".jpg":
        Image.open(tmp).convert("RGB").save(out, quality=82)
        tmp.unlink()
    return f"made {name}"


# the toast as a phone video: four moments of the same toast, each a Muse Image edit of the toast photo,
# filmed "handheld" (slow push + small shake) with quick pans between them, under David's spoken toast
TOAST_BEATS = [
    "David standing at the backyard table, raising a glass of wine and speaking to his mother, mid-sentence, "
    "the others looking up at him; seen from across the table, slightly wider than the reference photo.",
    "Close-up of grandmother Ruth listening to the toast, one hand on her chest, eyes shining, smiling; "
    "Maya beside her holding her other hand; string lights blurred behind.",
    "Ruth laughing through happy tears while Noam and Lia lean in to hug her from both sides; David still "
    "holding his glass in the foreground, out of focus.",
    "Everyone at the table raising their glasses toward Ruth, Ruth standing up and hugging David, "
    "the family cheering; warm evening light.",
]
TOAST_FRAMES = CACHE / "demo_toast"   # outside data/demo, so the scan never takes the frames for photos


def toast_clip(speech: Path, clip: Path, size: str = "1536x1024") -> None:
    TOAST_FRAMES.mkdir(parents=True, exist_ok=True)
    frames = [TOAST_FRAMES / f"beat_{k}.png" for k in range(len(TOAST_BEATS))]

    def one(k: int) -> None:
        if not frames[k].exists():
            generate(f"Candid phone video still, {FAMILY}, at Ruth's 70th birthday dinner in the backyard at dusk, "
                     f"the same table, clothes and lights as the reference toast photo. {TOAST_BEATS[k]}",
                     frames[k], references=[OUT / "IMG_20251012_190210.png", REF], size=size)
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, range(len(frames))))
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                        str(speech)], capture_output=True, text=True, check=True)
    total, fps, pan = float(r.stdout.strip()) + 0.6, 30, 0.35
    seg = (total + pan * (len(frames) - 1)) / len(frames)
    n = round(seg * fps)
    ins, parts = [], []
    for k, f in enumerate(frames):
        ins += ["-loop", "1", "-t", f"{seg:.3f}", "-i", str(f)]
        # handheld: a slow push in, a slow sway and a faint fast tremor, different phase per beat
        parts.append(f"[{k}:v]scale=1920:-2,zoompan=z='1.04+0.0009*on'"
                     f":x='iw/2-(iw/zoom/2)+14*sin(on/17+{k})+4*sin(on/3.3)'"
                     f":y='ih/2-(ih/zoom/2)+9*sin(on/23+{2 * k})+3*sin(on/2.9)'"
                     f":d={n}:s=1280x854:fps={fps},setsar=1,format=yuv420p[b{k}]")
    chain, last = [], "b0"
    for k in range(1, len(frames)):
        off = k * (seg - pan)
        chain.append(f"[{last}][b{k}]xfade=transition=smoothleft:duration={pan}:offset={off:.3f}[x{k}]")
        last = f"x{k}"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *ins, "-i", str(speech), "-filter_complex",
                    ";".join(parts + chain), "-map", f"[{last}]", "-map", f"{len(frames)}:a",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac", "-shortest",
                    str(clip)], check=True)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy(REF, OUT / "IMG_20251012_184500.png")  # the reference party photo itself
    with ThreadPoolExecutor(6) as ex:
        for msg in ex.map(lambda kv: make(*kv), SHOTS.items()):
            print(msg, flush=True)

    # WhatsApp-style duplicate of the party photo: smaller, recompressed, new name
    wa = OUT / "IMG-20251013-WA0004.jpg"
    if not wa.exists():
        img = Image.open(OUT / "IMG_20251012_184500.png").convert("RGB")
        img.thumbnail((1280, 1280))
        img.save(wa, quality=60)

    # the toast video: a spoken toast (Windows speech) under a handheld clip of the toast
    speech = OUT / "blessing.wav"
    if not speech.exists():
        text = ("Mom, seventy years, and you still dance faster than all of us. Thank you for every "
                "Friday dinner, every story, and every challah. We love you. Happy birthday!")
        ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              f"$s.SetOutputToWaveFile('{speech}'); $s.Speak(\"{text}\"); $s.Dispose()")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    clip = OUT / "VID_20251012_190500.mp4"
    if not clip.exists():
        toast_clip(speech, clip)
    voice = OUT / "AUD_20251012_191000.wav"
    if not voice.exists():
        shutil.copy(speech, voice)
    speech.unlink(missing_ok=True)
    print(sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
