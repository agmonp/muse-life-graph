"""Run the hosted demo's site mode on this computer, from data/site_bundle, for testing before a deploy.

    python scripts/run_site_local.py [--port 8802] [--data <folder>] [--gpu local]

Same code path as Modal: media copies, access code (MLG_SITE_CODE, default "localtest"), names read-only.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "data" / "site_bundle"

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8802)
    ap.add_argument("--data", default=str(BUNDLE / "data"), help="caches and films (e.g. a copy pulled from the site)")
    ap.add_argument("--gpu", default="pc", help="pc = wait for the GPU bridge, local = this computer's GPU")
    a = ap.parse_args()
    os.environ.update(MLG_DATA=a.data, MLG_SITE_MEDIA=str(BUNDLE / "media"),
                      MLG_SITE_CODE=os.environ.get("MLG_SITE_CODE", "localtest"), MLG_GPU=a.gpu)
    sys.path.insert(0, str(ROOT))
    import uvicorn
    uvicorn.run("mlg.web.app:app", host="127.0.0.1", port=a.port)
