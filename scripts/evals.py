"""Measure the system on the owner's real library and the site's real films; write docs/EVALS.md.

    .venv\\Scripts\\python.exe scripts\\evals.py [--films data/site_pull/films] [--skip-blind] [--report-only]

Films are the finished films of the hosted demo, copied down with
    python -m modal volume get mlg-site /data/films data/site_pull
    python -m modal volume get mlg-site /data/cache/usage.jsonl data/site_pull/usage.jsonl

1. Identity     - face fingerprints alone (YuNet + SFace against reference faces only) vs the owner's earlier
                  Life Graph, which says who is in each photo: precision and recall per photo and person.
2. Face groups  - purity of the "Who is this?" groups: automatically on faces whose person is known, and a
                  sample of open groups checked by eye (verdicts in docs/evals/group_check.json).
3. Blind test   - Muse Wonder watches the first cut and the re-cut of every finished film, in both orders,
                  not told which is the revision.
4. Narration    - a separate Muse Spark judge: does the picture under each narration line show what it says?
5. Time and $   - per film, from the crew log and the site's API usage log.
6. Spark Open   - Muse Spark Open on Baseten vs the Muse Spark API (scripts/eval_spark_open.py).
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from mlg import faces  # noqa: E402
from mlg.config import CACHE, ROOT, settings  # noqa: E402
from mlg.graph.db import session  # noqa: E402
from mlg.muse import chat  # noqa: E402
from mlg.perceive.keyframes import keyframes  # noqa: E402
from mlg.studio import critic as film_critic  # noqa: E402

REPORT = ROOT / "docs" / "EVALS.md"
RESULTS = CACHE / "evals.json"
PHOTO_MAP = CACHE / "lifegraph_photo_people.json"
GROUP_CHECK = ROOT / "docs" / "evals" / "group_check.json"
SHEETS = CACHE / "eval_groups"
# $ per 1M tokens (input, output), dev.meta.ai pricing 2026-10-26; Spark Open on Baseten lists the same as Spark
PRICES = {"muse-spark-1.3": (1.25, 4.25), "muse-spark-1.2": (1.25, 4.25), "muse-wonder-1.0": (4.00, 20.00),
          "meta-models/muse-spark-open-1026": (1.25, 4.25)}
THRESHOLDS = [(0.40, 0.0), (0.50, 0.0), (0.50, 0.10), (0.62, 0.10)]   # (similarity, margin over the next person)
SELF_MATCH = 0.95   # a face this close to a reference IS that reference picture: left out of the test


def cost(model: str | None, usage: dict | None) -> float:
    if model not in PRICES or not usage:
        return 0.0
    i = usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0
    o = usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
    return i / 1e6 * PRICES[model][0] + o / 1e6 * PRICES[model][1]


def fb_id(path: str) -> str:
    return Path(path).stem.split("_")[-1]


def local(path: str) -> Path:
    """Films made on the site name media copies under /site/media; the same copies are in the site bundle."""
    if path.startswith("/site/media/"):
        return ROOT / "data" / "site_bundle" / "media" / Path(path).name
    return Path(path)


# ---------------- 1. identity ----------------

def identity() -> dict:
    """Who is in each photo, by face fingerprints alone, against the earlier Life Graph's photo-level answer.

    The earlier graph knows who is in a photo but not where; the new graph's own links partly used it as a
    second key, so they are not a fair test. Here only reference faces count as the person's fingerprints (no
    linked faces), each face in a photo goes to its best person, one face per person, and the photo's set of
    predicted people is compared with the earlier graph's set, for the people that have reference faces."""
    photo_map = {k: set(v) for k, v in json.loads(PHOTO_MAP.read_text(encoding="utf-8")).items()}
    con = faces._con()
    obs = [o for o in faces._observations() if o["kind"] == "photo" and fb_id(o["path"]) in photo_map]
    refs = {}
    for pid, crops in faces._all_refs().items():
        rv = list(faces._vectors(con, [f"ref:{c}" for c in crops]).values())
        if rv:
            refs[pid] = np.stack(rv)
    vecs = faces._vectors(con, [o["id"] for o in obs])
    by_photo: dict[str, list[dict]] = defaultdict(list)
    for o in obs:
        by_photo[o["sha"]].append(o)
    scored = []          # per photo: truth set, [(face, [(score, pid), ...])]
    self_matches = 0
    for sha, group in by_photo.items():
        truth = photo_map[fb_id(group[0]["path"])] & set(refs)
        rows = []
        for o in group:
            v = vecs.get(o["id"])
            if v is None:
                continue
            per = {pid: m @ v for pid, m in refs.items()}
            if max(float(s.max()) for s in per.values()) >= SELF_MATCH:
                self_matches += 1
                continue
            rows.append(sorted(((float(np.mean(np.sort(s)[-3:])), pid) for pid, s in per.items()), reverse=True))
        scored.append((truth, rows))
    out = {"photos": len(scored), "faces": sum(len(r) for _, r in scored), "people_with_refs": len(refs),
           "no_face_left": sum(max(0, len(t) - len(r)) for t, r in scored),
           "left_out_self_matches": self_matches, "truth_pairs": sum(len(t) for t, _ in scored), "thresholds": []}
    for thr, margin in THRESHOLDS:
        tp = fp = fn = 0
        for truth, rows in scored:
            cands = []
            for k, sc in enumerate(rows):
                second = sc[1][0] if len(sc) > 1 else 0.0
                if sc[0][0] >= thr and sc[0][0] - second >= margin:
                    cands.append((sc[0][0], k, sc[0][1]))
            pred, used = set(), set()
            for s, k, pid in sorted(cands, reverse=True):
                if k not in used and pid not in pred:
                    used.add(k)
                    pred.add(pid)
            tp += len(pred & truth)
            fp += len(pred - truth)
            fn += len(truth - pred)
        out["thresholds"].append({"sim": thr, "margin": margin, "tp": tp, "fp": fp, "fn": fn,
                                  "precision": tp / max(1, tp + fp), "recall": tp / max(1, tp + fn)})
    # the deployed links (owner answers + two-key) on the same photos, for reference
    linked = defaultdict(set)
    for o in obs:
        if o["person"]:
            linked[o["sha"]].add(o["person"])
    tp = fp = fn = 0
    for sha, group in by_photo.items():
        truth = photo_map[fb_id(group[0]["path"])]
        pred = linked.get(sha, set())
        tp, fp, fn = tp + len(pred & truth), fp + len(pred - truth), fn + len(truth - pred)
    out["deployed"] = {"tp": tp, "fp": fp, "fn": fn, "precision": tp / max(1, tp + fp), "recall": tp / max(1, tp + fn)}
    out["owner"] = owner_answers()
    return out


def owner_answers() -> dict:
    """The owner's own answers on "Who is this?" against the machine's guess at the time."""
    with session() as s:
        rows = s.run("""MATCH (o:Observation) WHERE o.user_action IS NOT NULL OR o.candidate_person IS NOT NULL
                        OPTIONAL MATCH (p:Person)-[r:OBSERVED_AS]->(o)
                        RETURN o.user_action AS ua, o.candidate_person AS cand, p.id AS pid,
                               r.confirmed_by AS by""").data()
    judged = [r for r in rows if r["ua"] == "confirm" and r["cand"]]
    return {"answered": sum(1 for r in rows if r["ua"]), "with_guess": len(judged),
            "guess_right": sum(r["cand"] == r["pid"] for r in judged)}


# ---------------- 2. face groups ----------------

def group_purity() -> dict:
    """Cluster every face whose person is known with the same rule the "Who is this?" screen uses, and see
    whether each group holds one person (purity) and how many groups one person is split into."""
    con = faces._con()
    obs = [o for o in faces._observations() if o["person"]]
    vecs = faces._vectors(con, [o["id"] for o in obs])
    obs = [o for o in obs if o["id"] in vecs]
    _, members = faces.cluster(obs, vecs)
    multi = [m for m in members if len(m) >= 2]
    major = sum(Counter(o["person"] for o in m).most_common(1)[0][1] for m in multi)
    in_multi = sum(len(m) for m in multi)
    split = defaultdict(set)
    for k, m in enumerate(multi):
        for o in m:
            split[o["person"]].add(k)
    return {"faces": len(obs), "people": len({o["person"] for o in obs}), "groups": len(members),
            "groups_2plus": len(multi), "faces_in_2plus": in_multi,
            "purity": major / max(1, in_multi),
            "pure_groups": sum(1 for m in multi if len({o["person"] for o in m}) == 1) / max(1, len(multi)),
            "singletons": sum(1 for m in members if len(m) == 1),
            "groups_per_person_median": statistics.median(len(v) for v in split.values()) if split else None,
            "hand": json.loads(GROUP_CHECK.read_text(encoding="utf-8")) if GROUP_CHECK.exists() else None}


def group_sheets(n: int = 12, seed: int = 11) -> None:
    """Contact sheets of a random sample of open groups (3+ faces) for the check by eye; never committed."""
    from PIL import Image
    from mlg.perceive.crops import person_crop
    g = faces.groups()["groups"]
    pick = [x for x in g if x["size"] >= 3]
    random.Random(seed).shuffle(pick)
    SHEETS.mkdir(parents=True, exist_ok=True)
    obs = {o["id"]: o for o in faces._observations()}
    for k, x in enumerate(pick[:n]):
        tiles = []
        for f in x["faces"][:8]:
            o = obs[f["id"]]
            c = person_crop(o["path"], o["kind"], o["bbox"], o["frame"], max_side=160)
            if c is not None:
                tiles.append(c.convert("RGB").resize((160, 160)))
        sheet = Image.new("RGB", (160 * max(1, len(tiles)), 160), "white")
        for i, t in enumerate(tiles):
            sheet.paste(t, (160 * i, 0))
        sheet.save(SHEETS / f"group_{k:02d}_{x['size']}faces.jpg", quality=85)
    print(f"wrote {min(n, len(pick))} sheets to {SHEETS}")


# ---------------- 3. blind test ----------------

def _pair(a: Path, b: Path) -> dict:
    return chat.ask([chat.text("CUT A:"), chat.video(a), chat.text("CUT B:"), chat.video(b)],
                    system=film_critic.PAIR, model=settings().heavy_model, schema=film_critic.PAIR_SCHEMA,
                    schema_name="pair", effort="medium", max_tokens=6000).data


def blind(films: list[Path]) -> dict:
    """Both orders per film: a judge that prefers whatever it sees first would split 1-1 on every film."""
    rows = []
    for d in films:
        v1, v2 = d / "v1" / "film.mp4", d / "v2" / "film.mp4"
        if not (v1.exists() and v2.exists()):
            continue
        st = json.loads((d / "state.json").read_text(encoding="utf-8"))
        first = _pair(v1, v2)    # v1 shown as A
        second = _pair(v2, v1)   # v2 shown as A
        w1 = {"A": "v1", "B": "v2"}.get(first["better"], "same")
        w2 = {"A": "v2", "B": "v1"}.get(second["better"], "same")
        v = st.get("versions", {})
        rows.append({"film": d.name, "title": st.get("title"), "v1_first": w1, "v2_first": w2,
                     "verdict": w1 if w1 == w2 else "split", "reason": (second if w2 == "v2" else first)["reason"],
                     "score_v1": v.get("v1", {}).get("score"), "score_v2": v.get("v2", {}).get("score"),
                     "at_make_time": (st.get("blind") or {}).get("winner")})
        print("blind", d.name, w1, w2, flush=True)
    return {"films": rows, "v2": sum(r["verdict"] == "v2" for r in rows), "v1": sum(r["verdict"] == "v1" for r in rows),
            "split": sum(r["verdict"] == "split" for r in rows),
            "v2_votes": sum((r["v1_first"] == "v2") + (r["v2_first"] == "v2") for r in rows),
            "votes": 2 * len(rows)}


# ---------------- 4. narration vs picture ----------------

JUDGE = ("You check a personal film. You see one picture and the line the narrator says over it. "
         "Answer `match` if the picture clearly shows what the line says, `partly` if some of it, `no` if the "
         "picture contradicts it or shows something else. Be strict about people, actions and objects named.")
JUDGE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["verdict", "reason"],
                "properties": {"verdict": {"type": "string", "enum": ["match", "partly", "no"]},
                               "reason": {"type": "string"}}}


def _picture(shot: dict) -> Path | None:
    p = local(shot["path"])
    if not p.exists():
        return None
    if p.suffix.lower() in (".mp4", ".mov", ".webm", ".3gp"):
        frames = keyframes(p)
        return frames[len(frames) // 2][1] if frames else None
    return p


def _judge(pic: Path, line: str) -> str:
    ans = chat.ask([chat.text(f"NARRATION: {line}"), chat.image(pic)], system=JUDGE, schema=JUDGE_SCHEMA,
                   schema_name="match", effort="low", max_tokens=1500)
    return ans.data["verdict"]


def narration(films: list[Path]) -> dict:
    after, before = [], []
    for d in films:
        sb = json.loads((d / "storyboard.json").read_text(encoding="utf-8"))
        edl = json.loads((d / "edl_v2.json").read_text(encoding="utf-8"))
        first_shot = {}
        for s in edl["shots"]:
            if s["kind"] in ("still", "clip") and s.get("path"):
                first_shot.setdefault(s.get("scene"), s)
        for sc in sb["script"]["scenes"]:
            shot = first_shot.get(sc["order"])
            pic = _picture(shot) if shot else None
            if not pic or not sc.get("narration"):
                continue
            after.append(_judge(pic, sc["narration"]))
            if sc.get("narration_before_check"):
                before.append((_judge(pic, sc["narration_before_check"]), after[-1]))
    share = lambda xs, v: sum(x == v for x in xs) / max(1, len(xs))  # noqa: E731
    return {"films": len(films), "lines": len(after), "match": share(after, "match"), "partly": share(after, "partly"),
            "no": share(after, "no"), "rewritten_by_checker": len(before),
            "rewritten_before_match": share([b for b, _ in before], "match"),
            "rewritten_after_match": share([a for _, a in before], "match")}


# ---------------- 5. time and cost ----------------

def time_cost(films: list[Path], usage_log: Path) -> dict:
    usage = [json.loads(x) for x in usage_log.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows = []
    for d in films:
        st = json.loads((d / "state.json").read_text(encoding="utf-8"))
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
        rows.append({"film": d.name, "title": st.get("title"), "minutes": round((t1 - t0 - waited) / 60, 2),
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
    idn, gp, bl, nr, tc = r["identity"], r["groups"], r.get("blind"), r["narration"], r["time_cost"]
    L = [f"# Evals ({r['when']})", "",
         "Measured on the owner's real library (3,080 photos and videos of one family, shared with consent) and on "
         "every finished film of the hosted demo. Generated by `scripts/evals.py`; raw numbers in "
         "`data/cache/evals.json`. Samples are small: read these as honest spot checks, not benchmarks.", "",
         "## 1. Who is in the photo: face fingerprints vs the earlier Life Graph", "",
         f"Truth: the owner's earlier Life Graph says who is in each photo (not where). Test: {idn['photos']:,} photos, "
         f"{idn['faces']:,} faces with a fingerprint, {idn['truth_pairs']:,} (photo, person) pairs for the "
         f"{idn['people_with_refs']} people who have reference faces. Fingerprints (YuNet + SFace) are matched against "
         f"reference faces only, never against faces already linked, and {idn['left_out_self_matches']} faces that are "
         "themselves a reference picture are left out. A \"wrong\" can also be a person the earlier graph missed.", "",
         "| rule | precision | recall | right | wrong | missed |", "|---|---|---|---|---|---|"]
    for t in idn["thresholds"]:
        rule = f"similarity ≥ {t['sim']:.2f}" + (f", {t['margin']:.2f} ahead of the next person" if t["margin"] else "")
        L.append(f"| {rule} | {pct(t['precision'])} | {pct(t['recall'])} | {t['tp']:,} | {t['fp']:,} | {t['fn']:,} |")
    d, o = idn["deployed"], idn["owner"]
    L += ["", f"The app links a face only when two keys agree (fingerprint ≥ 0.50 and the earlier graph saw the person "
          f"in that photo, or ≥ 0.62 alone with a 0.10 margin), so its own links on these photos are {pct(d['precision'])} "
          f"precise with {pct(d['recall'])} recall ({d['tp']:,} right, {d['fp']:,} not in the earlier graph). That "
          f"number leans on the earlier graph and is not an independent test; the table above is. Of all {idn['truth_pairs']:,} pairs, "
          f"{idn.get('no_face_left', 0):,} can never be matched: the photo has fewer usable faces than the people the earlier graph lists "
          "(turned away, too small, not detected). Every other miss is a face that was found but scored below the bar.", "",
          f"On the \"Who is this?\" screen the owner answered {o['answered']} faces by hand"
          + (f"; where the machine had a guess, it was right {o['guess_right']} of {o['with_guess']} times."
             if o["with_guess"] else " (no machine guess was stored for those faces, so they are not scored here)."), "",
          "## 2. Face groups (\"Who is this?\")", "",
          f"Unnamed faces are grouped so that one answer names many. On the {gp['faces']:,} faces whose person is known "
          f"({gp['people']} people), the same grouping rule makes {gp['groups_2plus']} groups of 2+ faces: "
          f"**{pct(gp['purity'])} of their faces belong to the group's main person** and {pct(gp['pure_groups'])} of "
          f"the groups are a single person. The rule splits rather than merges: a person spans a median of "
          f"{gp['groups_per_person_median']:g} group(s), and {gp['singletons']:,} faces stay alone. Most of these faces "
          "were linked with the help of the same fingerprints, so this is an upper bound; the check by eye below is "
          "on faces nobody has named.", ""]
    if gp.get("hand"):
        h = gp["hand"]
        L += [f"Checked by eye ({h['checked_by']}, {h['date']}): {h['sample']} random open groups of 3+ faces, "
              f"{sum(1 for g in h['groups'] if g['verdict'] == 'one person')} one person, "
              f"{sum(1 for g in h['groups'] if g['verdict'] == 'mixed')} mixed, "
              f"{sum(1 for g in h['groups'] if g['verdict'] == 'unsure')} unsure. {h.get('note', '')}", ""]
    L += ["## 3. Does the re-cut beat the first cut? Blind test", ""]
    if bl and bl["films"]:
        L += [f"Muse Wonder watched the first cut (v1) and the critic's re-cut (v2) of all {len(bl['films'])} finished "
              "films on the demo site, twice per film with the order swapped, never told which is the revision. "
              f"**v2 won {bl['v2_votes']} of {bl['votes']} viewings**; per film: v2 both times {bl['v2']}, v1 both "
              f"times {bl['v1']}, split {bl['split']} (a split means the order decided, not the cut).", "",
              "| film | v1 shown first | v2 shown first | critic score v1 → v2 | why (one line) |", "|---|---|---|---|---|"]
        for f in bl["films"]:
            L.append(f"| {f['title'] or f['film']} | {f['v1_first']} | {f['v2_first']} | {f['score_v1']} → "
                     f"{f['score_v2']} | {' '.join((f['reason'] or '').split())[:150].replace('|', '/')} |")
        L += ["", "The critic's own 1-10 scores barely move (a critic who gave the draft 6 gives the re-cut 6 too); "
              "the blind choice is the better signal, and the reason the crew now runs it after every film.", ""]
    L += ["## 4. Does the narration match the picture?", "",
          f"A separate Muse Spark 1.3 judge looked at the first picture under each of {nr['lines']} narration lines "
          f"in the {nr['films']} films:", "", "| match | partly | no |", "|---|---|---|",
          f"| {pct(nr['match'])} | {pct(nr['partly'])} | {pct(nr['no'])} |", "",
          (f"The Picture Checker rewrote {nr['rewritten_by_checker']} lines: the screenwriter's version matched its "
           f"picture {pct(nr['rewritten_before_match'])} of the time, the rewrite {pct(nr['rewritten_after_match'])}."
           if nr["rewritten_by_checker"] else "The Picture Checker rewrote no line in these films.")
          + " The judge is the same model family as the checker with a different prompt: a friendly judge.", "",
          *([(ROOT / "docs" / "evals" / "narration_note.md").read_text(encoding="utf-8").strip(), ""]
            if (ROOT / "docs" / "evals" / "narration_note.md").exists() else []),
          "## 5. Time and cost per film", "",
          f"Median **{tc['median_minutes']:.1f} min** and **${tc['median_dollars']:.2f}** of Meta model calls per film "
          "on the hosted demo (time waiting for the owner's answers excluded; Voice Transcribe and file uploads "
          "carry no token price in the log; cached replies cost nothing; MusicGen and the narrator run on the "
          "owner's GPU or a Modal A10G and are not in the $). The cost is mostly Muse Wonder: the Screenwriter reads the "
          "whole library's research notes (up to ~600k input tokens, about $2.40 a call), and a re-made film reuses "
          "cached replies (the second \"Taya Growing Up\": $0.43). Films started within the same minute share the usage "
          "log, so both of them count each other's calls (the two films at 16:57).", "",
          "| film | minutes | length | model calls | $ | slowest stages (s) |", "|---|---|---|---|---|---|"]
    for f in tc["films"]:
        slow = ", ".join(f"{k} {v}" for k, v in list(f["stage_seconds"].items())[:3])
        L.append(f"| {f['title'] or f['film']} | {f['minutes']} | {f['film_seconds'] or 0:.0f} s | {f['api_calls']} | "
                 f"{f['dollars']:.2f} | {slow} |")
    so = r.get("spark_open")
    if so:
        s = so["summary"]
        L += ["", "## 6. Muse Spark Open on Baseten vs the Muse Spark API", "",
              f"`scripts/eval_spark_open.py`, {so['when']}: the same 30 inputs, prompts, schemas and effort, uncached: "
              f"{s.get('search', {}).get('n', 0)} search questions (English and Hebrew) turned into people, years and "
              f"search words, and {s.get('checker', {}).get('n', 0)} Picture Checker scenes from the demo's films "
              f"({s.get('checker', {}).get('pictures', 0)} pictures). API = `{so['api_model']}`, "
              f"Spark Open = `{so['open_model']}`.", "",
              "| | Muse Spark API | Muse Spark Open (Baseten) |", "|---|---|---|",
              f"| answered | {s['api']['ok']}/{s['api']['of']} | {s['open']['ok']}/{s['open']['of']} |",
              f"| median latency | {s['api']['p50_s']} s | {s['open']['p50_s']} s |",
              f"| output tokens (of which reasoning) | {s['api']['out_tokens']:,} ({s['api']['reasoning_tokens']:,}) | "
              f"{s['open']['out_tokens']:,} ({s['open']['reasoning_tokens']:,}) |",
              f"| cost of the 30 calls (list price, same per token) | ${s['api']['cost']:.3f} | ${s['open']['cost']:.3f} |", ""]
        if "search" in s:
            q = s["search"]
            L.append(f"**Search understanding:** the same people, years and kinds on {q['agree']}/{q['n']} questions "
                     f"(people {q['people']}/{q['n']}, years {q['years']}/{q['n']}); search words overlap "
                     f"{pct(q['words_jaccard'])} (Jaccard).")
        if "checker" in s:
            c = s["checker"]
            L.append(f"**Picture Checker:** the same keep/drop on {c['keep_agree']}/{c['pictures']} pictures "
                     f"({c['agree']}/{c['n']} scenes fully agree), the same person framed on {c['focus_agree']}/"
                     f"{c['pictures']}, the same narration verdict on {c['narration_agree']}/{c['n']} scenes.")
        L += ["", so.get("note", ""), ""]
    L += ["## 7. Narrator", "",
          "`scripts/voice_eval.py`: 6 narration lines synthesised, transcribed back by Muse Voice Transcribe, "
          "word error rate: MMS-TTS 16.5%, **SeamlessM4T v2 5.1%** (the narrator since 2026-10-26).", ""]
    cw = ROOT / "docs" / "evals" / "copywriter.json"
    if cw.exists():
        rows = json.loads(cw.read_text(encoding="utf-8"))
        views = [w for r in rows for w in r["wins"]]
        L += ["## 8. Copywriter: host-voice narration vs the screenwriter's lines", "",
              f"`scripts/eval_copywriter.py` on {len(rows)} finished films: the Copywriter (Muse Wonder) rewrote "
              "each film's narration; Muse Spark, a different model, compared the two sets blind (A/B, both "
              f"orders) with every scene's evidence. **Rewritten lines preferred in {views.count('new')} of "
              f"{len(views)} viewings**; unsupported facts flagged: rewritten "
              f"{sum(r['invented']['new'] for r in rows)}, original {sum(r['invented']['old'] for r in rows)}; "
              f"the code guard sent {sum(len(r['kept']) for r in rows)} line(s) back to the original. A model "
              "judging text, not a person listening; examples in [evals/copywriter.md](evals/copywriter.md).", ""]
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--films", default=str(ROOT / "data" / "site_pull" / "films"))
    ap.add_argument("--usage", default=str(ROOT / "data" / "site_pull" / "usage.jsonl"))
    ap.add_argument("--skip-blind", action="store_true")
    ap.add_argument("--sheets", action="store_true", help="only write the contact sheets for the check by eye")
    ap.add_argument("--report-only", action="store_true", help="rewrite EVALS.md from the last evals.json")
    a = ap.parse_args()
    if a.sheets:
        group_sheets()
        return
    if a.report_only:
        out = json.loads(RESULTS.read_text(encoding="utf-8"))
    else:
        films = [d for d in sorted(Path(a.films).glob("film_*"))
                 if (d / "state.json").exists() and (d / "edl_v2.json").exists()
                 and json.loads((d / "state.json").read_text(encoding="utf-8")).get("status") == "done"]
        out = {"when": time.strftime("%Y-%m-%d %H:%M"), "identity": identity()}
        print("identity", json.dumps(out["identity"], indent=1), flush=True)
        out["groups"] = group_purity()
        print("groups", {k: v for k, v in out["groups"].items() if k != "hand"}, flush=True)
        out["time_cost"] = time_cost(films, Path(a.usage))
        out["narration"] = narration(films)
        print("narration", out["narration"], flush=True)
        prev = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else {}
        out["blind"] = prev.get("blind") if a.skip_blind else blind(films)
    so = CACHE / "spark_open_eval.json"
    if so.exists():
        out["spark_open"] = {k: v for k, v in json.loads(so.read_text(encoding="utf-8")).items() if k != "rows"}
        note = ROOT / "docs" / "evals" / "spark_open_note.md"
        out["spark_open"]["note"] = note.read_text(encoding="utf-8").strip() if note.exists() else ""
    out["groups"]["hand"] = json.loads(GROUP_CHECK.read_text(encoding="utf-8")) if GROUP_CHECK.exists() else None
    RESULTS.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    REPORT.write_text(report(out), encoding="utf-8")
    print(f"wrote {REPORT}")


if __name__ == "__main__":
    main()
