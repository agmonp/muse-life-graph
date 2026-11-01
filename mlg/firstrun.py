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
          "neo4j_user": "NEO4J_USER", "neo4j_password": "NEO4J_PASSWORD"}
SECRET = {"meta_key", "baseten_key", "neo4j_password"}


def _mask(v: str) -> str:
    return f"…{v[-4:]}" if len(v) > 8 else ("set" if v else "")


def status() -> dict:
    s = settings()
    cur = {"meta_key": s.api_key, "baseten_key": s.baseten_key, "neo4j_uri": s.neo4j_uri,
           "neo4j_user": s.neo4j_user, "neo4j_password": s.neo4j_password}
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


def _test_graph(uri: str, user: str, password: str) -> None:
    from mlg.graph import db
    d = db.connect(uri, user or "neo4j", password)
    try:
        d.verify_connectivity()
    finally:
        d.close()


def save(form: dict) -> dict:
    s = settings()
    old = {"meta_key": s.api_key, "baseten_key": s.baseten_key, "neo4j_uri": s.neo4j_uri,
           "neo4j_user": s.neo4j_user or "neo4j", "neo4j_password": s.neo4j_password}
    new = {k: (str(form.get(k) or "").strip() or old[k]) for k in FIELDS}
    if new["neo4j_uri"] and "://" not in new["neo4j_uri"]:
        new["neo4j_uri"] = "neo4j+s://" + new["neo4j_uri"]
    results: dict[str, dict] = {}
    for name, need, test in (("meta", new["meta_key"], lambda: _test_meta(new["meta_key"])),
                             ("graph", new["neo4j_uri"] and new["neo4j_password"],
                              lambda: _test_graph(new["neo4j_uri"], new["neo4j_user"], new["neo4j_password"])),
                             ("baseten", new["baseten_key"], lambda: _test_baseten(new["baseten_key"]))):
        if not need:
            results[name] = {"ok": name == "baseten", "message": "optional, not set" if name == "baseten" else "missing"}
            continue
        try:
            test()
            results[name] = {"ok": True, "message": "works"}
        except Exception as e:  # noqa: BLE001 - shown next to the field
            results[name] = {"ok": False, "message": _why(e)}
    if not (results["meta"]["ok"] and results["graph"]["ok"]):
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
