"""Measure the system and write docs/EVALS.md.

    .venv\\Scripts\\python.exe scripts\\evals.py [--films 6] [--skip-pairwise]

1. Identity      - demo family against a hand-checked truth table; real photos against the
                   owner's own answers on the "Who is this?" screen.
2. Picture/text  - does each narration line match its picture? A separate Muse Spark judge,
                   before and after the Picture Checker.
3. Critic        - v1 vs v2 scores, plus a blind A/B: Muse Wonder watches both cuts in random
                   order without knowing which one is the revision.
4. Time and cost - per film, from the crew log and the API usage log.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mlg.config import CACHE, ROOT, settings  # noqa: E402
from mlg.graph.db import session  # noqa: E402
from mlg.muse import chat  # noqa: E402
from mlg.muse.http import USAGE_LOG  # noqa: E402
from mlg.people import dataset_of  # noqa: E402
from mlg.perceive.keyframes import keyframes  # noqa: E402
from mlg.studio.make import FILMS  # noqa: E402

REPORT = ROOT / "docs" / "EVALS.md"
# $ per 1M tokens (input, output), dev.meta.ai pricing 2026-10-26 (same table as scripts/probe.py)
PRICES = {"muse-spark-1.3": (1.25, 4.25), "muse-spark-1.2": (1.25, 4.25), "muse-wonder-1.0": (4.00, 20.00)}

# Who is really in each demo picture. "seen" = checked by eye on the image; "prompt" = from the
# generation prompt in scripts/make_demo_set.py (the image was not re-checked by eye).
DEMO_TRUTH = {
    "IMG_20251012_190210.png": ({"ruth", "david", "maya", "noam", "lia"}, "seen"),
    "IMG_20250621_103000.png": ({"ruth", "noam"}, "seen"),
    "IMG_20240203_160000.png": ({"ruth", "david", "maya", "noam", "lia"}, "seen"),
    "IMG_20250815_171245.png": ({"david", "maya", "noam", "lia"}, "seen"),
    "IMG_20251012_181530.png": ({"ruth", "david", "maya", "noam", "lia"}, "prompt"),
    "IMG_20251012_184500.png": ({"ruth", "david", "maya", "noam", "lia"}, "prompt"),
    "IMG_20120905_201500.png": ({"ruth", "david", "maya"}, "prompt"),
    "scan_0007.jpg": ({"ruth", "david"}, "prompt"),
    "VID_20251012_190500.mp4": ({"ruth", "david", "maya", "noam", "lia"}, "prompt"),
}


def cost(model: str | None, usage: dict | None) -> float:
    if model not in PRICES or not usage:
        return 0.0
    i = usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0
    o = usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
    return i / 1e6 * PRICES[model][0] + o / 1e6 * PRICES[model][1]


# ---------------- 1. identity ----------------

def identity_demo() -> dict:
    with session() as s:
        rows = s.run("""MATCH (o:Observation)-[:IN]->(mi:MediaItem) WHERE o.bbox IS NOT NULL OR mi.kind <> 'audio'
                        OPTIONAL MATCH (p:Person)-[r:OBSERVED_AS]->(o)
                        RETURN mi.path AS path, o.id AS obs, p.id AS pid, r.confirmed_by AS by,
                               o.candidate AS cand""").data()
    linked, proposed = defaultdict(set), defaultdict(set)
    for r in rows:
        name = Path(r["path"]).name
        if name not in DEMO_TRUTH:
            continue
        if r["pid"] and r["by"] == "user":
            # the owner answered: that face counts as asked, judged by the machine's guess at the time
            if r["cand"]:
                proposed[name].add(r["cand"].split(":")[1])
        elif r["pid"]:
            linked[name].add(r["pid"].split(":")[1])
        elif r["cand"]:
            proposed[name].add(r["cand"].split(":")[1])
    tp = sum(len(linked[n] & t) for n, (t, _) in DEMO_TRUTH.items())
    fp = sum(len(linked[n] - t) for n, (t, _) in DEMO_TRUTH.items())
    total = sum(len(t) for t, _ in DEMO_TRUTH.values())
    p_ok = sum(len(proposed[n] & t) for n, (t, _) in DEMO_TRUTH.items())
    p_all = sum(len(proposed[n]) for n in DEMO_TRUTH)
    missed = [f"{p} in {n}" for n, (t, _) in DEMO_TRUTH.items() for p in sorted(t - linked[n] - proposed[n])]
    return {"links": tp + fp, "correct": tp, "wrong": fp, "people_in_pictures": total,
            "precision": tp / max(1, tp + fp), "recall": tp / max(1, total),
            "asked_owner": p_all, "asked_and_right": p_ok, "neither_linked_nor_asked": missed,
            "seen_by_eye": sum(1 for _, how in DEMO_TRUTH.values() if how == "seen"), "pictures": len(DEMO_TRUTH)}


def identity_real() -> dict:
    """The owner's answers are the truth: how often did the machine's proposal agree?"""
    with session() as s:
        rows = s.run("""MATCH (o:Observation)-[:IN]->(mi:MediaItem)
                        OPTIONAL MATCH (p:Person)-[r:OBSERVED_AS]->(o)
                        RETURN mi.path AS path, o.user_action AS ua, o.candidate AS cand,
                               o.candidate_verdict AS verdict, p.id AS pid, r.confirmed_by AS by""").data()
    rows = [r for r in rows if dataset_of(r["path"]) == "real"]
    judged = [r for r in rows if r["ua"] == "confirm" and r["cand"]]
    agree = [r for r in judged if r["cand"] == r["pid"]]
    same = [r for r in judged if r["verdict"] == "same"]
    return {"faces_answered_by_owner": sum(1 for r in rows if r["ua"]),
            "confirmed_with_a_machine_guess": len(judged), "machine_guess_right": len(agree),
            "verifier_said_same": len(same), "verifier_same_right": sum(r["cand"] == r["pid"] for r in same),
            "auto_linked_two_key": sum(1 for r in rows if r["by"] == "two-key"),
            "still_unknown": sum(1 for r in rows if not r["pid"] and not r["ua"])}


# ---------------- 2. picture / text ----------------

JUDGE = ("You check a personal film. You see one picture and the line the narrator says over it. "
         "Answer `match` if the picture clearly shows what the line says, `partly` if some of it, `no` if the "
         "picture contradicts it or shows something else. Be strict about people, actions and objects named.")
JUDGE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["verdict", "reason"],
                "properties": {"verdict": {"type": "string", "enum": ["match", "partly", "no"]},
                               "reason": {"type": "string"}}}


def _picture(shot: dict) -> Path | None:
    p = Path(shot["path"])
    if p.suffix.lower() in (".mp4", ".mov", ".webm", ".3gp"):
        frames = keyframes(p)
        return frames[len(frames) // 2][1] if frames else None
    return p if p.exists() else None


def _judge(pic: Path, line: str) -> str:
    ans = chat.ask([chat.text(f"NARRATION: {line}"), chat.image(pic)], system=JUDGE, schema=JUDGE_SCHEMA,
                   schema_name="match", effort="low", max_tokens=1500)
    return ans.data["verdict"]


def picture_text(films: list[Path]) -> dict:
    after, before = [], []
    for d in films:
        sb = json.loads((d / "storyboard.json").read_text(encoding="utf-8"))
        edl = json.loads((d / "edl_v1.json").read_text(encoding="utf-8"))
        first_shot = {}
        for s in edl["shots"]:
            if s["kind"] in ("still", "clip", "title"):
                first_shot.setdefault(s.get("scene"), s)
        for sc in sb["script"]["scenes"]:
            shot = first_shot.get(sc["order"])
            pic = _picture(shot) if shot else None
            if not pic:
                continue
            if sc.get("narration"):
                after.append(_judge(pic, sc["narration"]))
            if sc.get("narration_before_check"):
                # what the screenwriter wrote, judged on the picture the scene ended up opening with
                before.append((_judge(pic, sc["narration_before_check"]), _judge(pic, sc["narration"])))
    share = lambda xs, v: sum(x == v for x in xs) / max(1, len(xs))  # noqa: E731
    return {"lines": len(after), "match": share(after, "match"), "partly": share(after, "partly"),
            "no": share(after, "no"), "rewritten_by_checker": len(before),
            "rewritten_before_match": share([b for b, _ in before], "match"),
            "rewritten_after_match": share([a for _, a in before], "match")}


# ---------------- 3. critic ----------------

PAIR = ("You are judging two cuts of the same short personal film, A and B. They use the same photos; one "
        "may be shorter, re-ordered or re-captioned. Ignore resolution and sharpness differences - judge only "
        "the editing: pacing, order, captions and the ending. Which cut is better?")
PAIR_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["better", "reason"],
               "properties": {"better": {"type": "string", "enum": ["A", "B", "same"]},
                              "reason": {"type": "string"}}}


def critic(films: list[Path], pairwise: int) -> dict:
    rows = []
    for d in films:
        st = json.loads((d / "state.json").read_text(encoding="utf-8"))
        v = st.get("versions", {})
        if v.get("v1", {}).get("score") is not None and v.get("v2", {}).get("score") is not None:
            rows.append({"film": d.name, "v1": v["v1"]["score"], "v2": v["v2"]["score"],
                         "applied": len(st.get("applied", []))})
    blind = []
    rng = random.Random(7)
    for r in rows[:pairwise]:
        d = FILMS / r["film"]
        v1, v2 = d / "v1" / "film.mp4", d / "v2" / "film.mp4"
        if not (v1.exists() and v2.exists()):
            continue
        flip = rng.random() < 0.5
        a, b = (v2, v1) if flip else (v1, v2)
        ans = chat.ask([chat.text("CUT A:"), chat.video(a), chat.text("CUT B:"), chat.video(b)], system=PAIR,
                       model=settings().heavy_model, schema=PAIR_SCHEMA, schema_name="pair", effort="medium",
                       max_tokens=6000).data
        winner = {"A": "v2" if flip else "v1", "B": "v1" if flip else "v2", "same": "same"}[ans["better"]]
        blind.append({"film": r["film"], "winner": winner, "reason": ans["reason"]})
    deltas = [r["v2"] - r["v1"] for r in rows]
    return {"films": rows, "mean_v1": statistics.mean(r["v1"] for r in rows) if rows else None,
            "mean_v2": statistics.mean(r["v2"] for r in rows) if rows else None,
            "improved": sum(x > 0 for x in deltas), "same": sum(x == 0 for x in deltas),
            "worse": sum(x < 0 for x in deltas), "blind": blind}


# ---------------- 4. time and cost ----------------

def time_cost(films: list[Path]) -> dict:
    usage = [json.loads(x) for x in USAGE_LOG.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows = []
    for d in films:
        st = json.loads((d / "state.json").read_text(encoding="utf-8"))
        if st.get("status") != "done" or not st["log"]:
            continue
        t0 = st["created"]
        t1 = st.get("finished") or t0 + st["log"][-1]["t"]
        waited = (st.get("timing") or {}).get("waiting_for_owner", 0)
        calls = [u for u in usage if t0 <= u["t"] <= t1 + 5]
        by_model = defaultdict(float)
        for u in calls:
            by_model[u.get("model") or u["path"]] += cost(u.get("model"), u.get("usage"))
        stages = defaultdict(float)   # time until the next log line, summed per crew member
        for a, b in zip(st["log"], st["log"][1:]):
            stages[a["who"]] += b["t"] - a["t"]
        rows.append({"film": d.name, "minutes": round((t1 - t0 - waited) / 60, 2),
                     "film_seconds": st["versions"].get("v2", {}).get("duration"), "api_calls": len(calls),
                     "dollars": round(sum(by_model.values()), 3),
                     "dollars_by_model": {k: round(v, 3) for k, v in by_model.items() if v},
                     "stage_seconds": {k: round(v) for k, v in sorted(stages.items(), key=lambda x: -x[1])}})
    return {"films": rows,
            "median_minutes": statistics.median(r["minutes"] for r in rows) if rows else None,
            "median_dollars": statistics.median(r["dollars"] for r in rows) if rows else None}


# ---------------- report ----------------

def pct(x: float | None) -> str:
    return "-" if x is None else f"{100 * x:.0f}%"


def report(r: dict) -> str:
    idd, idr, pt, cr, tc = r["identity_demo"], r["identity_real"], r["picture_text"], r["critic"], r["time_cost"]
    L = [f"# Evals ({time.strftime('%Y-%m-%d %H:%M')})", "",
         "Generated by `scripts/evals.py`; raw numbers in `data/cache/evals.json`. Small samples - "
         "read these as honest spot checks, not benchmarks.", "",
         "## 1. Who is in the picture", "",
         f"**Demo family** ({idd['pictures']} pictures, {idd['people_in_pictures']} people in them; "
         f"{idd['seen_by_eye']} pictures checked by eye, the rest from their generation prompts):", "",
         "| | |", "|---|---|",
         f"| Faces linked to a person | {idd['links']} |",
         f"| ...of which wrong | **{idd['wrong']}** (precision {pct(idd['precision'])}) |",
         f"| People found out of all people in the pictures | {pct(idd['recall'])} |",
         f"| Unsure faces left for the owner to confirm | {idd['asked_owner']} "
         f"(the machine's guess was right on {idd['asked_and_right']}) |",
         f"| Missed entirely | {', '.join(idd['neither_linked_nor_asked']) or 'none'} |", "",
         "The two-key rule (a Perceive match must pass a face-only check) trades recall for precision: "
         "it would rather ask than put the wrong name in a film.", "",
         f"**Owner's real photos** (truth = the owner's answers): {idr['faces_answered_by_owner']} faces answered; "
         f"where the machine had a guess, it was right {idr['machine_guess_right']} of "
         f"{idr['confirmed_with_a_machine_guess']} times; the face-verifier's \"same\" was right "
         f"{idr['verifier_same_right']} of {idr['verifier_said_same']}; {idr['auto_linked_two_key']} faces "
         f"auto-linked by two-key; {idr['still_unknown']} faces still unknown.", "",
         "## 2. Does the narration match the picture", "",
         f"A separate Muse Spark 1.3 judge looked at the picture under each of {pt['lines']} narration lines:", "",
         f"| match | partly | no |", "|---|---|---|",
         f"| {pct(pt['match'])} | {pct(pt['partly'])} | {pct(pt['no'])} |", "",
         (f"The Picture Checker rewrote {pt['rewritten_by_checker']} lines: the screenwriter's version matched its "
          f"picture {pct(pt['rewritten_before_match'])} of the time, the rewrite {pct(pt['rewritten_after_match'])}."
          if pt["rewritten_by_checker"] else
          "In these films the Picture Checker kept every narration line (it only rewrites lines the picture "
          "contradicts).") + " The judge is the same model family as the checker with a different prompt - a "
         "friendly judge.", "",
         "## 3. Does the critic make the film better", "",
         f"Self-scores over {len(cr['films'])} films: v1 mean {cr['mean_v1'] or 0:.1f} -> v2 mean "
         f"{cr['mean_v2'] or 0:.1f}; improved {cr['improved']}, same {cr['same']}, worse {cr['worse']}.", ""]
    if cr["blind"]:
        wins = sum(b["winner"] == "v2" for b in cr["blind"])
        L += [f"**Blind A/B** (Muse Wonder sees both cuts in random order, not told which is the revision): "
              f"v2 preferred in {wins} of {len(cr['blind'])}.", "",
              "| film | blind pick | why |", "|---|---|---|"]
        L += [f"| {b['film']} | {b['winner']} | {' '.join(b['reason'].split())[:180].replace('|', '/')} |"
              for b in cr["blind"]]
        L.append("")
    L += ["## 4. Time and cost per film", "",
          f"Median {tc['median_minutes']:.1f} min and ${tc['median_dollars']:.2f} of Meta API calls per film "
          "(excluding time waiting for the owner; Voice Transcribe and file uploads have no token price in the "
          "log and are not counted; cached replies cost nothing). MusicGen and the narrator run on the local GPU.",
          "", "| film | minutes | film length | API calls | $ | slowest stages (s) |", "|---|---|---|---|---|---|"]
    for f in tc["films"]:
        slow = ", ".join(f"{k} {v}" for k, v in list(f["stage_seconds"].items())[:3])
        L.append(f"| {f['film']} | {f['minutes']} | {f['film_seconds'] or 0:.0f} s | {f['api_calls']} | "
                 f"{f['dollars']} | {slow} |")
    L += ["", "## 5. Narrator", "",
          "`scripts/voice_eval.py`: 6 narration lines synthesised, transcribed back by Muse Voice Transcribe, "
          "word error rate: MMS-TTS 16.5%, **SeamlessM4T v2 5.1%** (the narrator since 2026-10-26).", ""]
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--films", type=int, default=6, help="how many recent finished films to judge")
    ap.add_argument("--skip-pairwise", action="store_true")
    ap.add_argument("--report-only", action="store_true", help="rewrite EVALS.md from the last evals.json")
    a = ap.parse_args()
    if a.report_only:
        REPORT.write_text(report(json.loads((CACHE / "evals.json").read_text(encoding="utf-8"))), encoding="utf-8")
        return
    done = [d for d in sorted(FILMS.glob("film_*"), reverse=True)
            if (d / "state.json").exists() and (d / "edl_v1.json").exists()
            and json.loads((d / "state.json").read_text(encoding="utf-8")).get("status") == "done"]
    recent = done[: a.films]
    out = {"identity_demo": identity_demo(), "identity_real": identity_real()}
    print("identity", json.dumps(out, indent=1), flush=True)
    out["picture_text"] = picture_text(recent)
    print("picture/text", out["picture_text"], flush=True)
    out["critic"] = critic(done, 0 if a.skip_pairwise else a.films)
    print("critic", {k: v for k, v in out["critic"].items() if k != "films"}, flush=True)
    out["time_cost"] = time_cost(done)
    (CACHE / "evals.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    REPORT.write_text(report(out), encoding="utf-8")
    print(f"wrote {REPORT}")


if __name__ == "__main__":
    main()
