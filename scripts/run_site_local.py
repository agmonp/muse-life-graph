"""Run the hosted demo's site mode on this computer, from data/site_bundle, for testing before a deploy.

    python scripts/run_site_local.py [--port 8802]

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
    a = ap.parse_args()
    os.environ.update(MLG_DATA=str(BUNDLE / "data"), MLG_SITE_MEDIA=str(BUNDLE / "media"),
                      MLG_SITE_CODE=os.environ.get("MLG_SITE_CODE", "localtest"), MLG_GPU="pc")
    sys.path.insert(0, str(ROOT))
    import uvicorn
    uvicorn.run("mlg.web.app:app", host="127.0.0.1", port=a.port)
