"""Subtitles in the film's language: words said in another language get a translation before the cut.

Blessings arrive with an English line (blessings.py); words heard in a video do not - Perceive keeps them
as said. In an English film a Hebrew toast would otherwise be subtitled in Hebrew. Before the editor runs,
every line a film will show that lacks a translation is translated in one call, and the translation is
written back to the graph (Utterance.text_en) so the next film, and search, have it too.
"""
from __future__ import annotations

import json
import re

from mlg.graph.db import session
from mlg.muse import chat

# letters outside Latin: Hebrew, Arabic, Cyrillic, Greek, CJK ... (Latin-script languages are left to the model)
FOREIGN = re.compile(r"[Ͱ-ϿЀ-ӿ֐-׿؀-ۿ฀-๿぀-ヿ一-鿿가-힯]")

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["lines"],
    "properties": {"lines": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "english"],
        "properties": {"id": {"type": "string"},
                       "english": {"type": "string", "description": "the subtitle: natural spoken English"}}}}},
}


def needs(u: dict) -> bool:
    return bool(u.get("text")) and not u.get("text_en") and bool(FOREIGN.search(u["text"]))


def translate(storyboard: dict) -> list[str]:
    """Fills `text_en` on every line the film can show; returns notes for the crew log."""
    if storyboard["brief"].get("language", "en") != "en":
        return []
    ms = storyboard["moments"]
    used = {mid for sc in storyboard["script"]["scenes"] for mid in sc["moment_ids"]}
    todo = {u["id"]: u for mid in used if mid in ms for u in ms[mid].get("said") or [] if u.get("id") and needs(u)}
    if not todo:
        return []
    ans = chat.ask([chat.text(json.dumps([{"id": i, "said": u["text"], "speaker": u.get("speaker")}
                                          for i, u in todo.items()], ensure_ascii=False))], system=(
        "You write English subtitles for a family film. Each line is what someone said on a home video, "
        "transcribed in its own language. Translate it into short, natural spoken English that keeps the "
        "warmth and the names (transliterate names: טאיה -> Taya). A song stays a song ('Today is a birthday, "
        "today is a birthday...'). Do not add anything that was not said."),
        schema=SCHEMA, schema_name="subtitles", effort="low", task="subtitles")
    done = {x["id"]: x["english"].strip() for x in ans.data.get("lines", []) if x.get("id") in todo and x.get("english")}
    for mid in used:
        for u in (ms.get(mid) or {}).get("said") or []:
            if u.get("id") in done:
                u["text_en"] = done[u["id"]]
    with session() as s:
        s.run("UNWIND $rows AS r MATCH (u:Utterance {id: r.id}) WHERE u.text_en IS NULL SET u.text_en = r.en",
              rows=[{"id": i, "en": en} for i, en in done.items()]).consume()
    return [f"'{todo[i]['text'][:40]}' -> '{en}'" for i, en in done.items()] + \
        ([f"served by {ans.served_by}"] if done else [])
