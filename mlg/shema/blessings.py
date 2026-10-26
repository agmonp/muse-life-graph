"""Blessings through a link: family and friends add their voice (and photos) to someone's film.

The owner opens a request for one person; anyone with the link records a short
blessing in the browser. Each recording is transcribed (Hebrew/English, Muse
Voice Transcribe), Muse Spark 1.2 listens to it and picks the lines worth putting
in a film (with an English translation for subtitles), and everything is written
to the graph as a Blessing FOR that person - so the screenwriter can use it.

Privacy by design: recording is opt-in and per link, the contributor chooses
whether their voice may be used in films, and declining keeps only the text.
"""
from __future__ import annotations

import json
import re
import secrets
import shutil
import time
from pathlib import Path

from mlg.config import DATA, settings
from mlg.graph.db import session
from mlg.ingest.scan import connect, ingest_file
from mlg.muse import chat
from mlg.muse.media import sha256_file, to_wav
from mlg.muse.transcribe import transcribe
from mlg.perceive.schema import EMOTIONS

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS blessing_requests (
  token TEXT PRIMARY KEY, person_id TEXT NOT NULL, dataset TEXT NOT NULL, message TEXT, created REAL,
  open INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS blessing_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT NOT NULL, from_name TEXT, relation TEXT,
  consent_film INTEGER, kind TEXT, path TEXT, status TEXT, error TEXT, result TEXT, created REAL);
"""

ANALYSIS = {
    "type": "object", "additionalProperties": False,
    "required": ["language", "summary", "mood", "film_worthy"],
    "properties": {
        "language": {"type": "string"},
        "summary": {"type": "string", "description": "one English sentence: what the speaker says to the honoree"},
        "mood": {"type": "string", "enum": list(EMOTIONS)},
        "film_worthy": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["t0", "t1", "text", "text_en", "why"],
            "properties": {
                "t0": {"type": "number"}, "t1": {"type": "number"},
                "text": {"type": "string", "description": "verbatim, original language"},
                "text_en": {"type": "string", "description": "subtitle line: natural English with proper capitals "
                                                              "and punctuation (translated if not English)"},
                "why": {"type": "string"},
            }}},
    },
}
SYSTEM = (
    "You listen to a short recorded blessing for {name} ({relation_of}), recorded by {speaker} "
    "({relation}). You get the audio and its transcript with turn timings. Pick 1-3 film-worthy "
    "segments: short, clear, emotionally strong lines (a wish, a memory, a laugh, 'I love you') that "
    "can play on their own in a film, 3-15 seconds each. Use the transcript timings for t0/t1 (seconds); "
    "never cut in the middle of a sentence. Quote the original words exactly in `text`, and write `text_en` as "
    "a clean subtitle: English, capitalised and punctuated (transcripts have no punctuation), translated if the "
    "speaker did not speak English. Judge mood only from what you hear. Do not analyse the speaker's "
    "personality.")


def _con():
    con = connect()
    con.executescript(SCHEMA_SQL)
    return con


def media_dir(dataset: str, token: str) -> Path:
    # the demo family's blessings live under data/demo so dataset_of() keeps them in that dataset
    root = DATA / "demo" / "blessings" if dataset == "demo" else DATA / "media" / "blessings"
    d = root / token
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_request(person_id: str, dataset: str, message: str = "") -> str:
    token = secrets.token_urlsafe(9)
    con = _con()
    con.execute("INSERT INTO blessing_requests VALUES (?,?,?,?,?,1)", (token, person_id, dataset, message, time.time()))
    con.commit()
    return token


def request_info(token: str) -> dict | None:
    row = _con().execute("SELECT * FROM blessing_requests WHERE token=?", (token,)).fetchone()
    if not row:
        return None
    info = dict(row)
    with session() as s:
        p = s.run("MATCH (p:Person {id: $id}) RETURN p.name AS name, p.relation AS relation, p.ref_crop AS crop",
                  id=info["person_id"]).single()
    info.update(name=p["name"] if p else "", relation=(p["relation"] if p else "") or "",
                crop=p["crop"] if p else None)
    return info


def list_requests() -> list[dict]:
    con = _con()
    out = []
    for r in con.execute("SELECT * FROM blessing_requests ORDER BY created DESC"):
        d = dict(r)
        d["items"] = [dict(x) for x in con.execute(
            "SELECT id, from_name, relation, kind, status, error, result, consent_film FROM blessing_items "
            "WHERE token=? ORDER BY created", (r["token"],))]
        for it in d["items"]:
            it["result"] = json.loads(it["result"]) if it["result"] else None
        out.append(d)
    return out


def save(token: str, from_name: str, relation: str, consent_film: bool, filename: str, data: bytes,
         kind: str) -> int:
    info = request_info(token)
    if not info or not info["open"]:
        raise ValueError("this blessing link is closed")
    safe = re.sub(r"[^\w.\-]+", "_", f"{int(time.time())}_{from_name}_{filename}")[:120]
    path = media_dir(info["dataset"], token) / safe
    path.write_bytes(data)
    con = _con()
    cur = con.execute("INSERT INTO blessing_items (token, from_name, relation, consent_film, kind, path, status, "
                      "created) VALUES (?,?,?,?,?,?,?,?)",
                      (token, from_name, relation, int(consent_film), kind, str(path), "received", time.time()))
    con.commit()
    return cur.lastrowid


def _set(item_id: int, **kw) -> None:
    con = _con()
    con.execute(f"UPDATE blessing_items SET {', '.join(f'{k}=?' for k in kw)} WHERE id=?", (*kw.values(), item_id))
    con.commit()


def process(item_id: int) -> dict:
    con = _con()
    it = dict(con.execute("SELECT * FROM blessing_items WHERE id=?", (item_id,)).fetchone())
    info = request_info(it["token"])
    try:
        if it["kind"] != "audio":
            # photos and videos join the normal pipeline (perceive, faces, graph) with the blessing as context
            from mlg.perceive.run import perceive_item
            from mlg.people import roster
            ingest_file(con, Path(it["path"]))
            con.commit()
            row = dict(con.execute("SELECT * FROM items WHERE path=?", (it["path"],)).fetchone())
            perceive_item(row, roster(info["dataset"]))
            _set(item_id, status="done", result=json.dumps({"kind": it["kind"]}))
            return {"kind": it["kind"]}
        _set(item_id, status="transcribing")
        # the WAV sits next to the original so it stays in the person's dataset (demo vs real)
        wav = Path(it["path"]).with_suffix(".wav")
        if not wav.exists():
            shutil.copy(to_wav(Path(it["path"]), 16000), wav)
        tr = transcribe(wav, languages=["Hebrew", "English"])
        _set(item_id, status="listening")
        system = SYSTEM.format(name=info["name"], relation_of=info["relation"] or "the honoree",
                               speaker=it["from_name"] or "a guest", relation=it["relation"] or "guest")
        ans = chat.ask([chat.text("Transcript:\n" + (tr.as_lines() or tr.text)), chat.audio(wav)],
                       system=system, model=settings().audio_model, schema=ANALYSIS, schema_name="blessing",
                       max_tokens=6000)
        res = ans.data
        res["transcript"] = tr.text
        res["duration_s"] = tr.duration_ms / 1000
        _write_graph(it, info, wav, res)
        _set(item_id, status="done", result=json.dumps(res, ensure_ascii=False))
        return res
    except Exception as e:  # noqa: BLE001 - shown on the owner's panel
        _set(item_id, status="failed", error=f"{type(e).__name__}: {e}"[:400])
        raise


def _write_graph(it: dict, info: dict, wav: Path, res: dict) -> None:
    """Blessing -> MediaItem + Moment (so the film crew finds it) + Utterances for the chosen lines."""
    con = _con()
    ingest_file(con, wav)
    con.commit()
    sha = sha256_file(wav)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    use_voice = bool(it["consent_film"])
    lines = [{"id": f"{sha}:b{i}", "text": x["text"], "text_en": x["text_en"], "t0": float(x["t0"]),
              "t1": float(x["t1"]), "why": x["why"]} for i, x in enumerate(res["film_worthy"], 1)]
    with session() as s:
        s.run("MATCH (n) WHERE n.id STARTS WITH $p DETACH DELETE n", p=f"{sha}:").consume()
        s.run("""MERGE (mi:MediaItem {id: $sha})
                 SET mi.path = $path, mi.kind = 'audio', mi.taken_at = $now, mi.date_source = 'recorded',
                     mi.effective_date = $now, mi.duration_s = $dur
                 MERGE (b:Blessing {id: $bid})
                 SET b.from_name = $from, b.relation = $rel, b.consent = $consent, b.summary = $summary,
                     b.language = $lang, b.created = $now
                 MERGE (b)-[:HAS_MEDIA]->(mi)
                 WITH b, mi MATCH (p:Person {id: $pid}) MERGE (b)-[:FOR]->(p)
                 CREATE (m:Moment {id: $mid, summary: $msum, start: $now, event_type: 'blessing',
                                   event_title: $title, date_source: 'recorded'})
                 CREATE (m)-[:DEPICTED_IN]->(mi)
                 WITH m, mi MATCH (e:Emotion {name: $mood}) MERGE (m)-[:EVOKED_EMOTION {intensity: 0.8}]->(e)""",
              sha=sha, path=str(wav), now=now, dur=res["duration_s"], bid=f"blessing:{it['id']}",
              **{"from": it["from_name"]}, rel=it["relation"], consent="film" if use_voice else "text_only",
              summary=res["summary"], lang=res["language"], pid=info["person_id"], mid=f"{sha}:moment",
              msum=f"{it['from_name']} ({it['relation']}) recorded a blessing for {info['name']}: {res['summary']}",
              title=f"Blessing for {info['name']} from {it['from_name']}", mood=(res.get("mood") or "").lower()).consume()
        if use_voice:
            s.run("""MATCH (mi:MediaItem {id: $sha}), (b:Blessing {id: $bid})
                     UNWIND $lines AS x
                     CREATE (u:Utterance {id: x.id, text: x.text, text_en: x.text_en, t0: x.t0, t1: x.t1,
                                          speaker_name: $from, why: x.why})
                     CREATE (u)-[:IN]->(mi) CREATE (b)-[:HAS_UTTERANCE]->(u)""",
                  sha=sha, bid=f"blessing:{it['id']}", lines=lines, **{"from": it["from_name"]}).consume()
