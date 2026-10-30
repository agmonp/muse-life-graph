"""The hosted demo on Modal: the same FastAPI app, plus Meta's audio models on a GPU.

    .venv\\Scripts\\python.exe scripts\\build_site_bundle.py            # reduced media copies -> data/site_bundle
    .venv\\Scripts\\python.exe -m modal volume put mlg-site data\\site_bundle /
    .venv\\Scripts\\python.exe -m modal secret create mlg-env --from-dotenv .env
    .venv\\Scripts\\python.exe -m modal secret create mlg-site-code MLG_SITE_CODE=<the access code>
    .venv\\Scripts\\python.exe -m modal deploy deploy\\modal_app.py

Volumes: `mlg-site` holds the media copies (/site/media), the caches and films (/site/data);
`mlg-hf` keeps the MusicGen and SeamlessM4T weights between runs. The graph stays on AuraDB.
Secrets: `mlg-env` (the project .env: Meta key, Neo4j) plus MLG_SITE_CODE, the access code.
"""
from __future__ import annotations

import os
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "muse-life-graph"
# The owner's own PC does the GPU work first, through scripts/gpu_bridge.py (free). With MLG_DEPLOY_GPU=1
# (needs a payment method on the Modal account) a Modal A10G takes over while the PC is off; without it,
# films made while the PC is off get on-screen captions instead of narration and score.
GPU = os.environ.get("MLG_DEPLOY_GPU") == "1"
app = modal.App(APP_NAME)
site_vol = modal.Volume.from_name("mlg-site", create_if_missing=True)
hf_vol = modal.Volume.from_name("mlg-hf", create_if_missing=True)
env = modal.Secret.from_name("mlg-env")
code = modal.Secret.from_name("mlg-site-code")   # MLG_SITE_CODE, the access code given to the judges

web_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("ffmpeg", "fonts-dejavu-core", "libraqm0")
    .pip_install_from_requirements(str(ROOT / "requirements.txt"))
    .pip_install("modal")
    .env({"MLG_DATA": "/site/data", "MLG_SITE_MEDIA": "/site/media", "MLG_GPU": "pc", "MLG_GPU_FALLBACK": "modal" if GPU else "none",
          "MLG_MODAL_APP": APP_NAME, "PYTHONPATH": "/app"})
    .add_local_dir(str(ROOT / "mlg"), "/app/mlg", ignore=["__pycache__", "*.pyc"])
)

gpu_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("torch==2.11.0", "transformers==5.20.2", "accelerate==1.15.0", "sentencepiece==0.2.2",
                 "soundfile==0.14.0", "protobuf==7.36.2", "numpy")
    .env({"HF_HOME": "/hf", "PYTHONPATH": "/app"})
    .add_local_file(str(ROOT / "mlg" / "studio" / "gpu_worker.py"), "/app/mlg/studio/gpu_worker.py")
    .add_local_file(str(ROOT / "mlg" / "studio" / "textnorm.py"), "/app/mlg/studio/textnorm.py")
    .add_local_file(str(ROOT / "mlg" / "__init__.py"), "/app/mlg/__init__.py")
    .add_local_file(str(ROOT / "mlg" / "studio" / "__init__.py"), "/app/mlg/studio/__init__.py")
)


def gpu_jobs(jobs: list[dict]) -> list[dict]:
    """MusicGen scores and SeamlessM4T narration: the same worker the local app runs, results as bytes."""
    import time
    from mlg.studio import gpu_worker
    out = []
    for job in jobs:
        t = time.perf_counter()
        try:
            res = gpu_worker.music(job) if job["type"] == "music" else gpu_worker.tts(job)
            res.update(ok=True, wall=round(time.perf_counter() - t, 1), wav=Path(job["out"]).read_bytes())
        except Exception as e:  # noqa: BLE001 - reported to the caller, who stops the film with the reason
            res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        out.append(res)
    hf_vol.commit()
    return out


if GPU:
    gpu_jobs = app.function(image=gpu_image, gpu="A10G", volumes={"/hf": hf_vol}, timeout=1800,
                            scaledown_window=300)(gpu_jobs)


@app.function(image=web_image, volumes={"/site": site_vol}, secrets=[env, code], timeout=3600,
              min_containers=1, max_containers=1, scaledown_window=1200)   # one container: films run in its threads
@modal.concurrent(max_inputs=40)
@modal.asgi_app()
def web():
    import threading
    from mlg.web.app import app as fastapi_app

    def keep():   # films and caches written by the app must outlive the container
        import time
        while True:
            time.sleep(60)
            try:
                site_vol.commit()
            except Exception:  # noqa: BLE001
                pass
    threading.Thread(target=keep, daemon=True).start()
    return fastapi_app
