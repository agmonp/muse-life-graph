"""Does the Copywriter make the narration better? A blind test on the films the hosted demo already made.

    python scripts/eval_copywriter.py [--films data/site_pull/films]

For every saved storyboard: the Copywriter (Muse Wonder) rewrites its narration, then Muse Spark - a
different model from the writer - reads the scenes, their evidence and the two narration sets, labelled
only A and B, and picks the better film narration. Each film is judged twice with the order swapped, so a
preference for "whatever comes first" cancels out. Writes docs/evals/copywriter.md and copywriter.json.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mlg.muse import chat  # noqa: E402
from mlg.studio import copywriter  # noqa: E402

OUT = ROOT / "docs" / "evals"

JUDGE = (
    "You judge the narration of a personal family film. You get the brief and each scene with what it is "
    "for, its emotion, its length and the evidence for its pictures, then two complete narration sets, A "
    "and B, one line per scene (null = silence). Pick the set that makes the better film for this occasion "
    "and tone: more moving or more fun as the tone asks, specific to this family, sounds like one host "
    "rather than photo captions, fits each scene's pictures and length. A line that states a fact the "
    "evidence doesn't support (a name, place, year or event) is a serious fault. Answer 'same' only if "
    "neither is better.")
JUDGE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["better", "reason", "invented_in"],
    "properties": {"better": {"type": "string", "enum": ["A", "B", "same"]},
                   "reason": {"type": "string"},
                   "invented_in": {"type": "array", "items": {"type": "string", "enum": ["A", "B"]},
                                   "description": "the sets that state a fact the evidence doesn't support"}},
}


def lines(sb: dict) -> dict:
    sc = sorted(sb["script"]["scenes"], key=lambda s: s["order"])
    return {"scenes": {s["order"]: s.get("narration") for s in sc}, "closing_card": sb["script"].get("closing_card")}


def judge(sb: dict, a: dict, b: dict) -> dict:
    ms = sb["moments"]
    scenes = [{"order": s["order"], "intent": s.get("intent"), "emotion": s.get("emotion"),
               "seconds": s.get("target_sec"), "evidence": copywriter.evidence(s, ms)}
              for s in sorted(sb["script"]["scenes"], key=lambda s: s["order"])]
    brief = {k: sb["brief"].get(k) for k in ("title", "occasion", "tone", "language")}
    msg = json.dumps({"brief": brief, "scenes": scenes, "A": a, "B": b}, ensure_ascii=False)
    return chat.ask([chat.text(msg)], system=JUDGE, schema=JUDGE_SCHEMA, schema_name="copy_judge",
                    effort="medium", max_tokens=4000, use_cache=False).data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--films", default=str(ROOT / "data" / "site_pull" / "films"))
    a = ap.parse_args()
    rows = []
    for p in sorted(Path(a.films).glob("*/storyboard.json")):
        sb = json.loads(p.read_text(encoding="utf-8"))
        state = p.parent / "state.json"
        if state.exists() and json.loads(state.read_text(encoding="utf-8")).get("status") != "done":
            continue   # failed attempts repeat a finished film's request
        if not any(s.get("narration") for s in sb["script"]["scenes"]):
            continue
        new = copy.deepcopy(sb)
        out = copywriter.rewrite(new)
        old_l, new_l = lines(sb), lines(new)
        v1 = judge(sb, old_l, new_l)       # A = old
        v2 = judge(sb, new_l, old_l)       # A = new
        wins = [{"A": "old", "B": "new"}.get(v1["better"], "same"), {"A": "new", "B": "old"}.get(v2["better"], "same")]
        invented = {"old": ("A" in v1["invented_in"]) + ("B" in v2["invented_in"]),
                    "new": ("B" in v1["invented_in"]) + ("A" in v2["invented_in"])}
        rows.append({"film": p.parent.name, "title": sb["script"].get("title"), "tone": sb["brief"].get("tone"),
                     "style": out["style"], "why": out["why"], "changed": len(out["changes"]), "kept": out["kept"],
                     "voiced": sum(1 for s in sb["script"]["scenes"] if s.get("narration")),
                     "wins": wins, "invented": invented, "reasons": [v1["reason"], v2["reason"]],
                     "old": old_l, "new": new_l})
        print(p.parent.name, out["style"], wins, invented, flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "copywriter.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    views = [w for r in rows for w in r["wins"]]
    n_new, n_old, n_same = views.count("new"), views.count("old"), views.count("same")
    inv_new = sum(r["invented"]["new"] for r in rows)
    inv_old = sum(r["invented"]["old"] for r in rows)
    md = [f"# Copywriter: blind test on {len(rows)} real films",
          "",
          "The Copywriter (Muse Wonder) rewrote each film's narration as one host voice; Muse Spark, a different "
          "model, read both narration sets labelled only A and B, with every scene's evidence, and picked the "
          "better film narration. Each film was judged in both orders. Script: `scripts/eval_copywriter.py`.",
          "",
          f"- **Rewritten lines preferred in {n_new} of {len(views)} viewings** (original {n_old}, no preference "
          f"{n_same}).",
          f"- Judge flagged an unsupported fact: rewritten {inv_new} times, original {inv_old} times "
          f"(out of {len(views)} viewings each).",
          f"- Lines the code guard sent back to the original (too long for the scene, or naming something the "
          f"scene's pictures don't show): {sum(len(r['kept']) for r in rows)}.",
          "",
          "| Film | Tone asked | Style chosen | Lines changed | Blind (both orders) |",
          "|---|---|---|---|---|"]
    md += [f"| {r['title']} | {r['tone']} | {r['style']} | {r['changed']} of {r['voiced']} | "
           f"{' / '.join(r['wins'])} |" for r in rows]
    md += ["", "## Examples", ""]
    for r in rows[:4]:
        md.append(f"**{r['title']}** ({r['style']})")
        md.append("")
        for k, old in r["old"]["scenes"].items():
            new = r["new"]["scenes"].get(k)
            if old != new:
                md.append(f"- before: {old or '(silence)'}  \n  after: {new or '(silence)'}")
        md.append("")
    (OUT / "copywriter.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"new {n_new} / old {n_old} / same {n_same}; invented new {inv_new} old {inv_old}")


if __name__ == "__main__":
    main()
