"""Lend this PC's GPU to the hosted site: music (MusicGen) and narration (SeamlessM4T) for its films.

    python scripts/gpu_bridge.py [--url https://...modal.run]

Every few seconds it asks the site for waiting GPU jobs (outgoing HTTPS only; nothing at home is
opened), runs them with the same local worker the app uses (.venv-gpu), and posts the audio back.
It proves itself with the site's access code (data/site_code.txt or MLG_SITE_CODE). While it is
not running, the site makes films with on-screen captions instead.
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from mlg.config import DATA  # noqa: E402
from mlg.studio import sound  # noqa: E402

SITE = "https://agmonporat--muse-life-graph-web.us-east.modal.run"
POLL_S = 3


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("MLG_SITE_URL", SITE))
    a = ap.parse_args()
    code = os.environ.get("MLG_SITE_CODE") or (DATA / "site_code.txt").read_text(encoding="utf-8").strip()
    headers = {"x-gpu-token": code}
    client = httpx.Client(timeout=60)
    print(f"bridge for {a.url}", flush=True)
    while True:
        try:
            r = client.get(f"{a.url}/api/gpu/next", headers=headers)
            r.raise_for_status()
            batch = r.json()
        except Exception as e:  # noqa: BLE001 - the site may be restarting or the PC offline; keep trying
            print(time.strftime("%H:%M:%S"), "poll failed:", str(e)[:200], flush=True)
            time.sleep(15)
            continue
        if not batch.get("id"):
            time.sleep(POLL_S)
            continue
        t0 = time.perf_counter()
        results = []
        with tempfile.TemporaryDirectory() as tmp:
            for i, job in enumerate(batch["jobs"]):
                out = Path(tmp) / f"{i}.wav"
                try:
                    sound.run_local([{**job, "out": str(out)}])
                    results.append({"ok": True, "wav_b64": base64.b64encode(out.read_bytes()).decode()})
                except Exception as e:  # noqa: BLE001 - reported back; the site stops that film with the reason
                    results.append({"ok": False, "error": f"{type(e).__name__}: {str(e)[:500]}"})
        try:
            client.post(f"{a.url}/api/gpu/result/{batch['id']}", headers=headers, json={"results": results},
                        timeout=300).raise_for_status()
            print(time.strftime("%H:%M:%S"), f"{len(results)} jobs in {time.perf_counter() - t0:.0f} s", flush=True)
        except Exception as e:  # noqa: BLE001
            print(time.strftime("%H:%M:%S"), "could not send results:", str(e)[:200], flush=True)


if __name__ == "__main__":
    main()
