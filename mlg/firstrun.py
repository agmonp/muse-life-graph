"""First run of the downloadable app: the user's own keys, tested, saved in their own folder.

The setup screen (/setup) sends what the user pasted; each part is tried for real before anything is
saved: a one-line Muse Spark call with their Meta key, a connection to their graph database (which also
creates the schema), and, if given, a Muse Spark Open call on Baseten. Only then are the values written to
%LOCALAPPDATA%/MuseLifeGraph/settings.env, which nothing but this app reads. A blank field keeps the value
already saved, so the screen also works for changing one key later.
"""
from __future__ import annotations

import os

from mlg import config
from mlg.config import settings

FIELDS = {"meta_key": "MODEL_API_KEY", "baseten_key": "BASETEN_API_KEY", "neo4j_uri": "NEO4J_URI",
          "neo4j_user": "NEO4J_USER", "neo4j_password": "NEO4J_PASSWORD",
          "mode": "MLG_MODE", "local_url": "MLG_LOCAL_URL", "local_model": "MLG_LOCAL_MODEL"}
SECRET = {"meta_key", "baseten_key", "neo4j_password"}
LOCAL_SERVERS = {"Ollama": "http://localhost:11434/v1", "LM Studio": "http://localhost:1234/v1"}
GLIMMER_GB = 24        # Muse Glimmer at ~4 bit with its drafter and vision encoder (Meta's release notes)


def _vram_gb() -> tuple[str, float]:
    """The biggest NVIDIA card and its memory, or ("", 0)."""
    import shutil
    import subprocess
    if not shutil.which("nvidia-smi"):
        return "", 0.0
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return "", 0.0
    cards = [(n.strip(), float(m) / 1024) for n, m in (ln.rsplit(",", 1) for ln in out.strip().splitlines() if "," in ln)]
    return max(cards, key=lambda c: c[1]) if cards else ("", 0.0)


def _ram_gb() -> float:
    import platform
    if platform.system() == "Windows":
        import ctypes

        class MEM(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + \
                       [(n, ctypes.c_ulonglong) for n in ("total", "avail", "ptotal", "pavail", "vtotal", "vavail", "x")]
        m = MEM()
        m.dwLength = ctypes.sizeof(MEM)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.total / 1024 ** 3
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
    except (ValueError, OSError, AttributeError):
        return 0.0


def _servers() -> list[dict]:
    """Local model servers that answer right now, with the models they offer."""
    import httpx
    found = []
    for name, url in LOCAL_SERVERS.items():
        try:
            r = httpx.get(f"{url}/models", timeout=2)
            if r.status_code == 200:
                found.append({"name": name, "url": url, "models": [m["id"] for m in r.json().get("data", [])]})
        except (httpx.HTTPError, ValueError):
            continue
    return found


def hardware() -> dict:
    """What this computer can do, and the mode to suggest: everything here, pictures here, or the cloud."""
    import platform
    gpu, vram = _vram_gb()
    ram = _ram_gb()
    apple = platform.system() == "Darwin" and platform.machine() == "arm64"   # unified memory serves the GPU
    room = ram * 0.75 if apple else vram
    if room >= GLIMMER_GB:
        mode, why = "local", f"{room:.0f} GB for the model: enough for Muse Glimmer, everything can run here."
    elif room >= 8:
        mode, why = "mixed", (f"{room:.0f} GB: a smaller picture model fits, so your pictures can stay here; "
                              "the film's writing goes to Meta's API as text.")
    else:
        mode, why = "cloud", "No graphics card with enough memory for a local model: Meta's API does the looking."
    return {"gpu": gpu or ("Apple silicon" if apple else ""), "vram_gb": round(vram, 1), "ram_gb": round(ram, 1),
            "suggest": mode, "why": why, "servers": _servers(), "glimmer_gb": GLIMMER_GB}


def _mask(v: str) -> str:
    return f"…{v[-4:]}" if len(v) > 8 else ("set" if v else "")


def _current() -> dict:
    s = settings()
    return {"meta_key": s.api_key, "baseten_key": s.baseten_key, "neo4j_uri": s.neo4j_uri,
            "neo4j_user": s.neo4j_user or "neo4j", "neo4j_password": s.neo4j_password, "mode": s.mode,
            "local_url": s.local_url, "local_model": s.local_model}


def status() -> dict:
    s = settings()
    cur = _current()
    return {"desktop": config.DESKTOP, "configured": s.configured(), "home": str(config.HOME),
            "values": {k: (_mask(v) if k in SECRET else v) for k, v in cur.items()}}


def _why(e: Exception) -> str:
    from mlg.muse.http import MuseError
    if isinstance(e, MuseError):
        if e.status in (401, 403):
            return "The key was not accepted. Copy it again from the provider's page."
        if e.status == 402:
            return "The account has no credit left."
        return f"The service answered {e.status}: {str(e)[:160]}"
    return f"{type(e).__name__}: {str(e)[:200]}"


def _test_meta(key: str) -> None:
    from mlg.muse.http import MetaHTTP
    MetaHTTP(api_key=key, timeout=60, tries=2).post("/chat/completions", {
        "model": settings().model, "max_tokens": 1000,
        "messages": [{"role": "user", "content": "Reply with the word OK."}]}, {"task": "setup"})


def _test_baseten(key: str) -> None:
    from mlg.muse.http import MetaHTTP
    s = settings()
    MetaHTTP(s.baseten_url, key, timeout=90, tries=1, provider="baseten").post("/chat/completions", {
        "model": s.baseten_model, "max_tokens": 2000,
        "messages": [{"role": "user", "content": "Reply with the word OK."}]}, {"task": "setup"})


def _test_local(url: str, model: str) -> None:
    """One small picture question to the local model: it must answer, and see."""
    import base64
    import io

    from PIL import Image

    from mlg.muse.http import MetaHTTP
    if not model:
        raise RuntimeError("Choose a model from your local server's list.")
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (217, 84, 42)).save(buf, "PNG")
    img = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    MetaHTTP(url, "local", timeout=300, tries=1, provider="local").post("/chat/completions", {
        "model": model, "max_tokens": 300,
        "messages": [{"role": "user", "content": [{"type": "text", "text": "One word: what colour is this square?"},
                                                  {"type": "image_url", "image_url": {"url": img}}]}]},
        {"task": "setup"})


def _test_graph(uri: str, user: str, password: str) -> None:
    from mlg.graph import db
    d = db.connect(uri, user or "neo4j", password)
    try:
        d.verify_connectivity()
    finally:
        d.close()


def save(form: dict) -> dict:
    from mlg.config import MODES
    old = _current()
    new = {k: (str(form.get(k) or "").strip() or old[k]) for k in FIELDS}
    new["mode"] = new["mode"] if new["mode"] in MODES else "cloud"
    if new["neo4j_uri"] and "://" not in new["neo4j_uri"]:
        new["neo4j_uri"] = "neo4j+s://" + new["neo4j_uri"]
    local = new["mode"] in ("local", "mixed")
    meta_needed = new["mode"] != "local"      # everything on this computer needs no key at all
    results: dict[str, dict] = {}
    for name, need, optional, test in (
            ("meta", new["meta_key"], not meta_needed, lambda: _test_meta(new["meta_key"])),
            ("local", local, not local, lambda: _test_local(new["local_url"], new["local_model"])),
            ("graph", new["neo4j_uri"] and new["neo4j_password"], False,
             lambda: _test_graph(new["neo4j_uri"], new["neo4j_user"], new["neo4j_password"])),
            ("baseten", new["baseten_key"], True, lambda: _test_baseten(new["baseten_key"]))):
        if not need:
            results[name] = {"ok": optional, "message": "not needed" if optional else "missing"}
            continue
        try:
            test()
            results[name] = {"ok": True, "message": "works"}
        except Exception as e:  # noqa: BLE001 - shown next to the field
            results[name] = {"ok": False, "message": _why(e)}
    if not (results["meta"]["ok"] and results["graph"]["ok"] and results["local"]["ok"]):
        return {"ok": False, "results": results}
    if not results["baseten"]["ok"]:
        new["baseten_key"] = ""            # a key that does not work is not kept; the app uses the Meta key
    config.HOME.mkdir(parents=True, exist_ok=True)
    lines = ["# Muse Life Graph: your own keys, written by the setup screen. Only this app reads this file."]
    lines += [f"{env}={new[k]}" for k, env in FIELDS.items() if new[k]]
    config.USER_ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for k, env in FIELDS.items():
        if new[k]:
            os.environ[env] = new[k]
        else:
            os.environ.pop(env, None)
    _reload()
    from mlg.graph import db
    db.apply_schema()
    return {"ok": True, "results": results}


def _reload() -> None:
    from mlg import library
    from mlg.graph import db
    settings.cache_clear()
    try:
        db.driver().close()
    except Exception:  # noqa: BLE001 - there was no driver yet
        pass
    db.driver.cache_clear()
    library.invalidate()
