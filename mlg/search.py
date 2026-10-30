"""Search and ask, over the life graph.

`search(q)`: Muse Spark reads the question once (any language) and turns it into
people, years, kinds and English search words; a full-text index over what Muse
saw in every moment (summary, event, objects, activities, place, words said,
album) ranks the moments; people and years filter. Each hit says why it was found.

`ask(q)`: the same search, then Muse Spark answers the question from the found
moments only and cites them, so every sentence points to real pictures.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading

from mlg import library
from mlg.muse import chat

_LOCK = threading.Lock()
_DB: dict = {"key": None, "con": None}

QUERY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["people", "year_from", "year_to", "kinds", "words", "must"],
    "properties": {
        "people": {"type": "array", "items": {"type": "string"}, "description": "ids from PEOPLE only"},
        "year_from": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "year_to": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "kinds": {"type": "array", "items": {"type": "string", "enum": ["photo", "video", "audio"]}},
        "words": {"type": "array", "items": {"type": "string"},
                  "description": "English search words and close synonyms for what should be seen or said"},
        "must": {"type": "array", "items": {"type": "string"},
                 "description": "the 1-2 words a result really must match, from `words`"},
    },
}

ANSWER_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["answer", "cited", "unsure"],
    "properties": {
        "answer": {"type": "string", "description": "2-5 sentences in the question's language; cite as [n]"},
        "cited": {"type": "array", "items": {"type": "integer"}},
        "unsure": {"type": "boolean", "description": "true when the moments do not really answer it"},
    },
}


def _index():
    """An in-memory FTS5 index, rebuilt whenever the library reloads."""
    ms, ppl = library.data()
    with _LOCK:
        if _DB["key"] is library._CACHE["key"] and _DB["con"] is not None:
            return _DB["con"], ms, ppl
        con = sqlite3.connect(":memory:", check_same_thread=False)
        con.execute("CREATE VIRTUAL TABLE t USING fts5(i UNINDEXED, what, things, place, said, album, "
                    "tokenize='porter unicode61')")
        for i, m in enumerate(ms):
            con.execute("INSERT INTO t VALUES (?,?,?,?,?,?)", (
                i, f"{m['summary'] or ''} {m['event'] or ''} {m['event_type'] or ''} {' '.join(m['mood'])}",
                " ".join(m["objects"] + m["activities"]),
                f"{m['place'] or ''} {m['place_type'] or ''}",
                " ".join(f"{u['text']} {u.get('text_en') or ''}" for u in m["said"]),
                m["album"] or ""))
        _DB.update(key=library._CACHE["key"], con=con)
        return con, ms, ppl


def understand(q: str) -> dict:
    _, ppl = library.data()
    roster = [{"id": pid, "name": p["name"], "relation": p.get("relation"), "owner": bool(p.get("owner"))}
              for pid, p in ppl.items()]
    ans = chat.ask([chat.text(f"QUESTION: {q}")], system=(
        "You turn a search over a personal photo and video library into filters. PEOPLE: "
        + json.dumps(roster, ensure_ascii=False)
        + "\nMatch names in any language or spelling to PEOPLE ids ('me'/'I'/'אני' = the owner). "
        "Years only when the question gives a time ('in 2012', 'as a child' -> leave null unless a birth year "
        "is known). kinds only when asked ('videos'). words: English words for what should be seen or said, "
        "with 2-4 close synonyms each (beach -> sea, sand, shore); leave out names and dates."),
        schema=QUERY_SCHEMA, schema_name="search_query", effort="low")
    d = ans.data
    d["people"] = [p for p in d.get("people", []) if p in ppl]
    return d


def _fts(words: list[str]) -> str:
    toks = [re.sub(r"[^\w]+", " ", w).strip() for w in words]
    return " OR ".join(f'"{t}"' for t in toks if t)


def search(q: str, limit: int = 60) -> dict:
    con, ms, ppl = _index()
    u = understand(q)
    scores: dict[int, float] = {}
    why: dict[int, set] = {}
    if u["words"] and (expr := _fts(u["words"])):
        for i, rank in con.execute("SELECT i, bm25(t, 3.0, 2.0, 1.5, 2.0, 1.0) FROM t WHERE t MATCH ? ", (expr,)):
            scores[int(i)] = -rank
        must = [w.lower() for w in u.get("must") or []]
        for i in list(scores):
            m = ms[i]
            hay = " ".join([m["summary"] or "", m["event"] or "", " ".join(m["objects"] + m["activities"]),
                            m["place"] or "", " ".join(u2["text"] for u2 in m["said"]), m["album"] or ""]).lower()
            hits = {w for w in u["words"] if w.lower() in hay}
            why[i] = hits
            if must and not any(w in hay for w in must):
                scores[i] *= 0.35          # matches only a synonym: keep it, lower
        # a broad word ("friends") matches half the library; keep the moments that match the main words,
        # unless that leaves too few to be useful
        if must:
            strong = {i for i in scores if why.get(i) and any(w.lower() in {h.lower() for h in why[i]} for w in must)}
            if len(strong) >= 8:
                scores = {i: s for i, s in scores.items() if i in strong}
            top = max(scores.values(), default=0)
            scores = {i: s for i, s in scores.items() if s >= 0.25 * top} or scores
    elif u["people"] or u["year_from"] or u["kinds"]:
        scores = {i: 1.0 for i in range(len(ms))}
    out = _filter(ms, ppl, u, scores, why, strict_people=True)
    relaxed = False
    if not out and u["people"] and scores:
        # few faces are named yet: keep what matches the words, the person's name may just not be linked
        out, relaxed = _filter(ms, ppl, u, scores, why, strict_people=False), True
    out.sort(key=lambda c: (-c["score"], c["date"]))
    return {"q": q, "understood": {"people": [ppl[p]["name"] for p in u["people"]], "years":
                                   [u["year_from"], u["year_to"]], "kinds": u["kinds"], "words": u["words"]},
            "relaxed": relaxed, "total": len(out), "results": out[:limit]}


def _filter(ms, ppl, u, scores, why, strict_people: bool) -> list[dict]:
    out = []
    names = {p: ppl[p]["name"].lower() for p in u["people"]}
    for i, s in scores.items():
        m = ms[i]
        if u["people"] and strict_people:
            text = (m["summary"] or "").lower()
            # in the picture by a linked face, or named in what Muse saw
            if not all(p in m["people"] or names[p] in text for p in u["people"]):
                continue
        y = int(m["date"][:4]) if m["date"][:4].isdigit() else None
        if u["year_from"] and (y is None or y < u["year_from"]):
            continue
        if u["year_to"] and (y is None or y > u["year_to"]):
            continue
        if u["kinds"] and m["kind"] not in u["kinds"]:
            continue
        reason = []
        if u["people"] and strict_people:
            reason.append(" & ".join(ppl[p]["name"] for p in u["people"]))
        if why.get(i):
            reason.append(", ".join(sorted(why[i])[:4]))
        c = library.card(m, ppl)
        c["why"] = " · ".join(reason)
        c["score"] = round(s, 3)
        out.append(c)
    return out


def ask(q: str) -> dict:
    found = search(q, limit=24)
    ms, ppl = library.data()
    by_id = {m["id"]: m for m in ms}
    rows = []
    for n, c in enumerate(found["results"], 1):
        m = by_id[c["id"]]
        rows.append({"n": n, "date": m["date"][:10], "how_dated": m["date_source"], "kind": m["kind"],
                     "people": [p["name"] for p in c["people"]], "seen": m["summary"], "place": m["place"],
                     "said": [u.get("text_en") or u["text"] for u in m["said"]][:3], "album": m["album"]})
    if not rows:
        return {**found, "answer": None, "cited": [], "unsure": True}
    ans = chat.ask([chat.text(f"QUESTION: {q}\nMOMENTS: {json.dumps(rows, ensure_ascii=False)}")], system=(
        "You answer the owner's question about their own life using ONLY the moments given (each is a real "
        "photo, video or voice note, described by what was seen and said). Cite moments as [n]. Say plainly "
        "what the moments do not show. Dates estimated from content are approximate - say 'around'. "
        "Never guess what people felt beyond what was seen. Answer in the question's language."),
        schema=ANSWER_SCHEMA, schema_name="answer", effort="low")
    cited = [n for n in ans.data.get("cited", []) if 1 <= n <= len(found["results"])]
    return {**found, "answer": ans.data.get("answer"), "unsure": ans.data.get("unsure", False),
            "cited": [found["results"][n - 1]["id"] for n in cited]}
