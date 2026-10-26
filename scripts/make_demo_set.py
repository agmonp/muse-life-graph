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

    # a short "video" of the toast photo with a spoken blessing (Windows speech)
    speech = OUT / "blessing.wav"
    if not speech.exists():
        text = ("Mom, seventy years, and you still dance faster than all of us. Thank you for every "
                "Friday dinner, every story, and every challah. We love you. Happy birthday!")
        ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              f"$s.SetOutputToWaveFile('{speech}'); $s.Speak(\"{text}\"); $s.Dispose()")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
    clip = OUT / "VID_20251012_190500.mp4"
    if not clip.exists():
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(OUT / "IMG_20251012_190210.png"),
                        "-i", str(speech), "-filter_complex",
                        "[0:v]scale=3072:-2,zoompan=z='1+0.0008*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                        ":d=10000:s=1280x854:fps=25[v]", "-map", "[v]", "-map", "1:a",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)], check=True)
    voice = OUT / "AUD_20251012_191000.wav"
    if not voice.exists():
        shutil.copy(speech, voice)
    speech.unlink(missing_ok=True)
    print(sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
