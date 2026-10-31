"""Muse Spark Open (Meta open weights, on Baseten) vs the Muse Spark API on the same 30 inputs.

    python scripts/eval_spark_open.py [--films data/site_pull/films]

15 search questions (how each model turns a question into people, years and search words) and 15 Picture
Checker scenes from the site's finished films (keep or drop each picture, who the camera frames). Both
models get the same prompt, schema and effort, uncached, one after the other. Writes
data/cache/spark_open_eval.json; scripts/evals.py puts it in docs/EVALS.md.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mlg.config import CACHE  # noqa: E402
from mlg.muse import chat  # noqa: E402

OUT = CACHE / "spark_open_eval.json"
PRICE = (1.25, 4.25)   # $ per million input / output tokens: the same list price for both (Baseten and Meta)
QUESTIONS = [
    "When did we go to the beach with the kids?",
    "Photos of Taya as a baby",
    "Adam's birthday parties",
    "Videos from India",
    "Who came to the wedding in 2017?",
    "Me and Tamar on holiday",
    "Poker nights with friends",
    "What did we do for Rosh Hashana in 2018?",
    "Hiking in the desert",
    "Boaz playing football",
    "תמונות של תאיה ואדם יחד",
    "מתי היינו בהודו?",
    "ארוחות שישי עם המשפחה",
    "Grandma's house in the 1980s",
    "Everyone singing happy birthday",
]


def _cost(u: dict) -> float:
    return (u.get("prompt_tokens", 0) * PRICE[0] + u.get("completion_tokens", 0) * PRICE[1]) / 1e6


def _run(fn) -> dict:
    t = time.perf_counter()
    try:
        out = fn()
        ans = out.pop("_answer")
        return {"ok": True, "out": out, "seconds": round(time.perf_counter() - t, 2), "usage": ans.usage,
                "cost": _cost(ans.usage), "provider": ans.provider, "fallback": ans.fallback}
    except Exception as e:  # noqa: BLE001 - a failure is a result
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}", "seconds": round(time.perf_counter() - t, 2)}


def search_cases() -> list[dict]:
    from mlg import search
    rows = []
    for q in QUESTIONS:
        r = {"input": q, "kind": "search"}
        for name, prov in (("api", chat.Provider.meta()), ("open", chat.Provider.baseten())):
            r[name] = _run(lambda: search.understand(q, provider=prov, use_cache=False))
        if r["api"]["ok"] and r["open"]["ok"]:
            a, b = r["api"]["out"], r["open"]["out"]
            wa, wb = {w.lower() for w in a["words"]}, {w.lower() for w in b["words"]}
            r["same_people"] = set(a["people"]) == set(b["people"])
            r["same_years"] = (a["year_from"], a["year_to"]) == (b["year_from"], b["year_to"])
            r["same_kinds"] = set(a["kinds"]) == set(b["kinds"])
            r["agree"] = r["same_people"] and r["same_years"] and r["same_kinds"]
            r["words_jaccard"] = round(len(wa & wb) / max(1, len(wa | wb)), 2)
        rows.append(r)
        print("search", q[:40], r.get("agree"), r["api"]["seconds"], r["open"]["seconds"], flush=True)
    return rows


def _local(path: str) -> str:
    """Storyboards from the site name media copies under /site/media; the same copies are in the bundle."""
    if path.startswith("/site/media/"):
        return str(ROOT / "data" / "site_bundle" / "media" / Path(path).name)
    return path


def checker_cases(films: Path, n: int = 15) -> list[dict]:
    from mlg.studio import checker
    scenes = []
    for sbp in sorted(films.glob("*/storyboard.json")):
        sb = json.loads(sbp.read_text(encoding="utf-8"))
        ms = {k: {**m, "path": _local(m["path"])} for k, m in sb["moments"].items()}
        for sc in sb["script"]["scenes"]:
            vis = [m for m in sc["moment_ids"] if m in ms and ms[m]["kind"] == "photo" and Path(ms[m]["path"]).exists()]
            if len(vis) >= 2:
                scenes.append((sbp.parent.name, {**sc, "moment_ids": vis[:4]}, ms))
    # spread over the films: every k-th scene
    step = max(1, len(scenes) // n)
    rows = []
    for film, sc, ms in scenes[::step][:n]:
        r = {"input": f"{film} scene {sc['order']}", "kind": "checker", "pictures": len(sc["moment_ids"])}
        for name, prov in (("api", chat.Provider.meta()), ("open", chat.Provider.baseten())):
            r[name] = _run(lambda: checker.check_scene(sc, ms, provider=prov, use_cache=False))
        if r["api"]["ok"] and r["open"]["ok"]:
            r["moment_ids"] = sc["moment_ids"]
            compare_checker(r)
        rows.append(r)
        print("checker", r["input"], r.get("agree"), r["api"]["seconds"], r["open"]["seconds"], flush=True)
    return rows


def compare_checker(r: dict) -> None:
    """Keep/drop and framing agreement per picture (ids compared without their ':moment' end)."""
    base = lambda m: (m or "").split(":")[0]  # noqa: E731
    va = {base(v["moment_id"]): v for v in r["api"]["out"]["verdicts"]}
    vb = {base(v["moment_id"]): v for v in r["open"]["out"]["verdicts"]}
    ids = [base(m) for m in r.get("moment_ids") or []] or sorted(set(va) | set(vb))
    both = [m for m in ids if m in va and m in vb]
    r["keep_agree"] = sum(va[m]["keep"] == vb[m]["keep"] for m in both)
    r["focus_agree"] = sum(va[m]["focus_person_id"] == vb[m]["focus_person_id"] for m in both)
    r["compared"] = len(both)
    r["narration_agree"] = r["api"]["out"]["narration_ok"] == r["open"]["out"]["narration_ok"]
    r["agree"] = r["keep_agree"] == len(both) == len(ids)


def summary(rows: list[dict]) -> dict:
    out = {}
    for name in ("api", "open"):
        ok = [r[name] for r in rows if r[name]["ok"]]
        secs = [x["seconds"] for x in ok]
        out[name] = {"ok": len(ok), "of": len(rows), "p50_s": round(statistics.median(secs), 2) if secs else None,
                     "mean_s": round(statistics.mean(secs), 2) if secs else None,
                     "cost": round(sum(x["cost"] for x in ok), 4),
                     "out_tokens": sum(x["usage"].get("completion_tokens", 0) for x in ok),
                     "reasoning_tokens": sum((x["usage"].get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
                                             for x in ok),
                     "fallbacks": sum(1 for x in ok if x.get("fallback"))}
    both = [r for r in rows if "agree" in r]
    out["compared"] = len(both)
    out["agree"] = sum(r["agree"] for r in both)
    s = [r for r in both if r["kind"] == "search"]
    c = [r for r in both if r["kind"] == "checker"]
    if s:
        out["search"] = {"n": len(s), "agree": sum(r["agree"] for r in s),
                         "people": sum(r["same_people"] for r in s), "years": sum(r["same_years"] for r in s),
                         "words_jaccard": round(statistics.mean(r["words_jaccard"] for r in s), 2)}
    if c:
        out["checker"] = {"n": len(c), "agree": sum(r["agree"] for r in c),
                          "pictures": sum(r["compared"] for r in c), "keep_agree": sum(r["keep_agree"] for r in c),
                          "focus_agree": sum(r["focus_agree"] for r in c),
                          "narration_agree": sum(r["narration_agree"] for r in c)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--films", default=str(ROOT / "data" / "site_pull" / "films"))
    ap.add_argument("--recompute", action="store_true", help="redo the comparison on the saved replies")
    a = ap.parse_args()
    if a.recompute:
        res = json.loads(OUT.read_text(encoding="utf-8"))
        for r in res["rows"]:
            if r["kind"] == "checker" and r["api"]["ok"] and r["open"]["ok"]:
                compare_checker(r)
        res["summary"] = summary(res["rows"])
        OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(json.dumps(res["summary"], indent=1))
        return
    rows = search_cases() + checker_cases(Path(a.films))
    res = {"when": time.strftime("%Y-%m-%d %H:%M"), "api_model": chat.Provider.meta().default_model,
           "open_model": chat.Provider.baseten().default_model, "summary": summary(rows), "rows": rows}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(res["summary"], indent=1))


if __name__ == "__main__":
    main()
