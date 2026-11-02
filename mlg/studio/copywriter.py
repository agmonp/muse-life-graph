"""The Copywriter: rewrites the narration of the whole film in one voice, like the host of a show.

The screenwriter decides what each scene is and writes a working line; after the Picture Checker has
settled which pictures stay, the copywriter reads every scene at once and rewrites the lines as one
spoken piece in a style that fits the occasion (nostalgic, playful or documentary): a hook, callbacks,
a build, a payoff. It may only use facts the archive has for that scene, so code checks every new
line: too long for its scene, or naming a person, place or year the scene's evidence doesn't have,
and the line keeps the screenwriter's words.

    MLG_COPYWRITER=0 turns it off.
"""
from __future__ import annotations

import json
import os
import re

from mlg.config import settings
from mlg.muse import chat

STYLES = {
    "nostalgic": "a warm host looking back - gentle, specific, a little wistful; lets small details carry the feeling",
    "playful": "an affectionate host who teases like family does - light jokes, comic timing, never mean",
    "documentary": "a calm, observant narrator - plain words, quiet wonder, lets the pictures speak",
}
WORDS_PER_SEC = 2.6    # the narrator reads about this fast; a line must fit its scene
MAX_WORDS = 16

SYSTEM = (
    "You are the COPYWRITER of a personal film made from a family's own photos and videos. The words you "
    "write are spoken by a narrator over the pictures, like the host of a show, and also appear as captions. "
    "You get the brief and every scene in order: what the scene does, its emotion, how long it lasts, its "
    "current narration line, and the evidence for its pictures (dates, places, events, who is in them, what "
    "was said).\n\n"
    "Pick ONE style that fits the occasion and tone, and keep it for the whole film:\n"
    + "\n".join(f"- {k}: {v}" for k, v in STYLES.items()) + "\n\n"
    "Then rewrite the lines so the film sounds written by one person:\n"
    "1. Open with a hook, build, and land a payoff in the last line; a callback to an earlier line is welcome.\n"
    "2. Speak to the audience or about the people - never describe the photo ('a photo of', 'we see', "
    "'pictured'). Say what the moment means to this family, through a concrete detail from its evidence.\n"
    "3. Facts only from that scene's evidence or the brief: names, places, years, events. Never invent a "
    "name, a place, an age, a year or a relation. If the evidence is thin, write about the feeling, not facts.\n"
    "4. Each line must be speakable within its scene: at most `max_words` words. Short sentences; commas and "
    "dashes give the narrator its pauses. No emoji, no hashtags, no quotation marks around the line.\n"
    "5. Keep a scene silent (narration null) where the current line is null, and you may make a weak line "
    "null when silence works better - but keep at least half of the voiced scenes voiced.\n"
    "6. Write in the brief's language. Also rewrite the closing card: one short line for the last frame.")

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["style", "why", "lines", "closing_card"],
    "properties": {
        "style": {"type": "string", "enum": list(STYLES)},
        "why": {"type": "string", "description": "one sentence: why this style for this film"},
        "lines": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["order", "narration"],
            "properties": {"order": {"type": "integer"},
                           "narration": {"anyOf": [{"type": "string"}, {"type": "null"}]}}}},
        "closing_card": {"type": "string"},
    },
}


def enabled() -> bool:
    return os.environ.get("MLG_COPYWRITER", "1").strip() not in ("0", "off", "false", "no")


def max_words(scene: dict) -> int:
    return max(4, min(MAX_WORDS, int(float(scene.get("target_sec") or 4) * WORDS_PER_SEC)))


def _names(m: dict) -> list[str]:
    out = []
    for f in (m.get("faces") or []) + (m.get("people") or []):
        n = f.get("name") if isinstance(f, dict) else f
        if isinstance(n, str) and n:
            out.append(n)
    return out


def evidence(scene: dict, moments: dict) -> list[dict]:
    """What the archive says about the scene's pictures - the only facts its line may use."""
    out = []
    for mid in scene["moment_ids"]:
        m = moments.get(mid)
        if not m:
            continue
        said = [s.get("text") if isinstance(s, dict) else s for s in (m.get("said") or [])]
        out.append({"date": (m.get("date") or "")[:10] or None, "kind": m.get("kind"), "event": m.get("event"),
                    "place": m.get("place"), "summary": m.get("summary"), "people": _names(m),
                    "said": [s for s in said if s][:3]})
    return out


def _words(line: str) -> list[str]:
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)?", line)


def _vocabulary(scene: dict, moments: dict, brief: dict, people: list[str]) -> set[str]:
    text = json.dumps(evidence(scene, moments), ensure_ascii=False) + " " + " ".join(
        [scene.get("narration") or "", scene.get("intent") or "", brief.get("title") or "",
         brief.get("subtitle") or "", brief.get("occasion") or ""] + people)
    return {w.lower() for w in _words(text)}


def unsupported(line: str, vocab: set[str]) -> list[str]:
    """Names and years in a line that the scene's evidence doesn't have: capitalised words that don't open a
    sentence, and four-digit numbers. Hebrew has no capitals, so there only years are checked."""
    bad = []
    for sent in re.split(r"(?<=[.!?…])\s+|\s+[–—-]\s+", line.strip()):
        for i, w in enumerate(_words(sent)):
            proper = i > 0 and w[:1].isupper() and w.lower() not in ("i", "i'm", "i've", "i'd", "i'll")
            year = w.isdigit() and len(w) == 4
            if (proper or year) and w.lower() not in vocab and w.lower().rstrip("s") not in vocab:
                bad.append(w)
    return bad


def rewrite(storyboard: dict, people: list[str] | None = None) -> dict | None:
    """Rewrites the script's narration in place. Returns what changed for the crew log, or None if off."""
    if not enabled():
        return None
    brief, script, ms = storyboard["brief"], storyboard["script"], storyboard["moments"]
    scenes = sorted(script["scenes"], key=lambda s: s["order"])
    people = people or sorted({n for m in ms.values() for n in _names(m)})
    payload = {
        "brief": {k: brief.get(k) for k in ("title", "subtitle", "occasion", "tone", "language", "notes")},
        "logline": script.get("logline"), "closing_card": script.get("closing_card"),
        "scenes": [{"order": s["order"], "beat": s.get("beat"), "intent": s.get("intent"),
                    "emotion": s.get("emotion"), "seconds": s.get("target_sec"), "max_words": max_words(s),
                    "has_spoken_voice": bool(s.get("voice_line_ids")), "narration": s.get("narration"),
                    "evidence": evidence(s, ms)} for s in scenes]}
    ans = chat.ask([chat.text(json.dumps(payload, ensure_ascii=False))], system=SYSTEM,
                   model=settings().heavy_model, schema=SCHEMA, schema_name="copy", effort="medium",
                   max_tokens=8000)
    data = ans.data
    by_order = {ln.get("order"): ln.get("narration") for ln in data.get("lines") or []}
    changes, kept = [], []
    voiced = [s for s in scenes if s.get("narration")]
    for s in voiced:
        if s["order"] not in by_order:
            continue
        new = (by_order[s["order"]] or "").strip().strip('"“”') or None
        old = s["narration"]
        if new == old:
            continue
        if new is not None:
            n = len(_words(new))
            bad = unsupported(new, _vocabulary(s, ms, brief, people))
            if n > max_words(s):
                kept.append(f"scene {s['order']}: kept the old line - the new one has {n} words for "
                            f"{s.get('target_sec')} s")
                continue
            if bad:
                kept.append(f"scene {s['order']}: kept the old line - the new one names {', '.join(bad)}, "
                            "which this scene's pictures don't show")
                continue
        changes.append({"order": s["order"], "before": old, "after": new})
    # silence is a choice, but a film that loses most of its voice is a different film
    if sum(1 for c in changes if c["after"] is None) > len(voiced) / 2:
        silenced = [c for c in changes if c["after"] is None]
        for c in silenced[len(voiced) // 2:]:
            changes.remove(c)
    for c in changes:
        s = next(x for x in scenes if x["order"] == c["order"])
        s["narration_before_copy"] = c["before"]
        s["narration"] = c["after"]
    card = (data.get("closing_card") or "").strip()
    if card and card != script.get("closing_card") and len(_words(card)) <= MAX_WORDS \
            and not unsupported(card, {w.lower() for w in _words(json.dumps(payload, ensure_ascii=False))}):
        script["closing_card_before_copy"] = script.get("closing_card")
        script["closing_card"] = card
    out = {"style": data.get("style"), "why": data.get("why", ""), "changes": changes, "kept": kept,
           "served_by": ans.served_by}
    storyboard["copy"] = out
    return out
