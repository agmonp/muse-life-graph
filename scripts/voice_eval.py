"""Narrator quality, measured: synthesize test lines, have Muse Voice Transcribe listen, score word error rate.

    .venv\\Scripts\\python.exe scripts\\voice_eval.py [--tag name] [--rate 0.92]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mlg.config import CACHE, ROOT  # noqa: E402
from mlg.muse.transcribe import transcribe  # noqa: E402

LINES = [
    "At the water's edge, a mother holds her laughing child.",
    "Ruth blows out the candles on her chocolate seventieth cake.",
    "A first dance under string lights, in 2012.",
    "Seventy candles, one big breath, and everyone laughing.",
    "Flour on her hands, and a grandson who won't stop giggling.",
    "Happy 70th birthday, Ruth. We love you.",
]
WORD_NUM = {"70th": "seventieth", "2012": "twenty twelve", "70": "seventy"}


def words(s: str) -> list[str]:
    s = s.lower()
    for k, v in WORD_NUM.items():
        s = s.replace(k, v)
    return re.findall(r"[a-z']+", s.replace("'", ""))


def wer(ref: str, hyp: str) -> float:
    r, h = words(ref), words(hyp)
    d = [[i + j if i * j == 0 else 0 for j in range(len(h) + 1)] for i in range(len(r) + 1)]
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (r[i - 1] != h[j - 1]))
    return d[-1][-1] / max(1, len(r))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="mms")
    ap.add_argument("--rate", type=float, default=0.92)
    ap.add_argument("--engine", default="mms")
    ap.add_argument("--speaker", type=int, default=4)
    a = ap.parse_args()
    out = CACHE / "voice_eval" / a.tag
    out.mkdir(parents=True, exist_ok=True)
    jobs = [{"type": "tts", "text": t, "lang": "eng", "rate": a.rate, "engine": a.engine, "speaker": a.speaker,
             "out": str(out / f"{i}.wav")} for i, t in enumerate(LINES)]
    spec = out / "jobs.json"
    spec.write_text(json.dumps(jobs), encoding="utf-8")
    r = subprocess.run([str(ROOT / ".venv-gpu" / "Scripts" / "python.exe"),
                        str(ROOT / "mlg" / "studio" / "gpu_worker.py"), str(spec)], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        res = json.loads(line)
        if not res.get("ok"):
            sys.exit(f"worker failed: {res.get('error')}")
    total = 0.0
    for i, t in enumerate(LINES):
        heard = transcribe(out / f"{i}.wav", languages=["English"], use_cache=False).text
        e = wer(t, heard)
        total += e
        print(f"{e:4.2f}  {t}\n      heard: {heard}")
    print(f"\n{a.tag}: mean WER {total / len(LINES):.3f}")


if __name__ == "__main__":
    main()
