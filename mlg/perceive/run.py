"""Perceive pass: every ingested, non-duplicate item -> Muse -> critic -> graph.

    python -m mlg.perceive.run [--limit N] [--workers 8] [--kind photo|video|audio] [--force]

Per item, one Muse call carries: the rules prompt, the known people's reference
crops (so identity is matched visually, not guessed), the neighbouring moments
already in the graph, and the media itself:
  photo -> the image                         (muse-spark-1.3)
  video -> timestamped keyframes + its audio (muse-spark-1.3, one Chat call)
  audio -> the audio + a diarized transcript (muse-spark-1.2 + Voice Transcribe)
Results are saved to data/perceptions/<sha>.json and written to Neo4j.
"""
from __future__ import annotations

import argparse
import copy
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pydantic import ValidationError

from mlg.config import DATA, ROOT, settings
from mlg.graph import write as graph_write
from mlg.graph.db import session
from mlg.ingest.scan import connect
from mlg.muse import chat
from mlg.muse.transcribe import transcribe
from mlg.perceive.critic import review
from mlg.perceive.keyframes import audio_track, keyframes
from mlg.perceive.schema import Perception, fill_missing, strict_schema
from mlg.perceive.verify import verify
from mlg.people import dataset_of, roster

OUT = DATA / "perceptions"
PROMPT = (ROOT / "mlg" / "prompts" / "perceive.md").read_text(encoding="utf-8")
SCHEMA = strict_schema()
WRITE_LOCK = threading.Lock()
TRUSTED_DATES = {"exif", "container", "filename"}


def neighbours(taken_at: str, sha: str, limit: int = 8) -> list[dict]:
    day = (taken_at or "")[:10]
    if not day:
        return []
    with session() as s:
        rows = s.run("""MATCH (m:Moment) WHERE m.start STARTS WITH $day AND NOT m.id STARTS WITH $sha
                        OPTIONAL MATCH (p:Person)-[:OBSERVED_AS]->(:Observation)-[:PRESENT_AT]->(m)
                        RETURN m.start AS when, m.summary AS summary, m.event_title AS event,
                               collect(DISTINCT p.name) AS people
                        ORDER BY m.start LIMIT $limit""", day=day, sha=sha, limit=limit)
        return [dict(r) for r in rows]


def context_for(path: str) -> dict | None:
    """What the person wrote around this item on Facebook/Instagram (album, caption, place)."""
    con = connect()
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='context'").fetchone():
        return None
    row = con.execute("SELECT * FROM context WHERE path=?", (path,)).fetchone()
    if not row:
        return None
    ctx = {k: row[k] for k in ("source", "album", "album_description", "place", "lat", "lon", "uploaded") if row[k]}
    if row["captions"]:
        ctx["captions"] = row["captions"][:1200]
    return ctx


def build_parts(item: dict, people: list[dict], near: list[dict]) -> tuple[str, list[chat.Part], str]:
    meta = {k: item.get(k) for k in ("kind", "taken_at", "date_source", "width", "height", "duration_s")}
    meta["file_name"] = Path(item["path"]).name
    if item["date_source"] == "upload":
        meta["note"] = ("taken_at is the social-media UPLOAD time; the photo may be much older "
                        "(scans, old prints) - estimate the real date from the content")
    elif item["date_source"] not in TRUSTED_DATES:
        meta["note"] = "no trusted capture date - estimate it from the content"
    if ctx := context_for(item["path"]):
        meta["posted_with"] = ctx
        meta["posted_with_note"] = ("the owner's own album name / caption / place for this item: strong "
                                    "context for event, place and people, but captions may be about "
                                    "something else (opinions, jokes) - do not over-trust them")
    known = [{"id": p["id"], "name": p["name"], "relation": p.get("relation"), "looks": p.get("note")}
             for p in people]
    system = PROMPT.format(media_id=item["sha256"], media_meta=json.dumps(meta, ensure_ascii=False),
                           known_people=json.dumps(known, ensure_ascii=False),
                           neighbours=json.dumps(near, ensure_ascii=False, default=str))
    parts: list[chat.Part] = []
    crops = [p for p in people if p.get("crop") and Path(p["crop"]).exists()][:12]
    if crops:
        parts.append(chat.text("REFERENCE PHOTOS OF KNOWN_PEOPLE (match people in the media against these):"))
        for p in crops:
            parts += [chat.text(f"{p['id']} = {p['name']}"), chat.image(p["crop"])]
    path = Path(item["path"])
    model = settings().model
    if item["kind"] == "photo":
        parts += [chat.text("THE MEDIA ITEM (a photo):"), chat.image(path)]
    elif item["kind"] == "video":
        frames = keyframes(path)
        parts.append(chat.text(f"THE MEDIA ITEM (a video, {item.get('duration_s') or 0:.1f} s): "
                               f"{len(frames)} keyframes in order, then its audio track. "
                               "Use `frame` = keyframe index for bboxes and `t` = seconds."))
        for i, (t, f) in enumerate(frames):
            parts += [chat.text(f"keyframe {i} at {t:.1f} s"), chat.image(f)]
        if (wav := audio_track(path)) is not None:
            parts += [chat.text("audio track:"), chat.audio(wav)]
        else:
            parts.append(chat.text("(this video has no audio track)"))
    else:
        tr = transcribe(path, languages=["Hebrew", "English"])
        model = settings().audio_model
        parts += [chat.text("THE MEDIA ITEM (an audio recording). Diarized transcript, turn-level times, "
                            "speaker labels are per recording, not identities:\n" + tr.as_lines()),
                  chat.audio(path)]
    return system, parts, model


def perceive_item(item: dict, people: list[dict], force: bool = False, redo: bool = False) -> dict:
    """force = ask Muse again; redo = re-run critic + graph write from cached Muse replies."""
    out = OUT / f"{item['sha256']}.json"
    if out.exists() and not (force or redo):
        return {"path": item["path"], "skipped": True}
    t0 = time.perf_counter()
    saved = json.loads(out.read_text(encoding="utf-8")) if redo and out.exists() else {}
    if saved.get("raw"):
        ans = chat.Answer(text="", data=saved["raw"], usage=saved.get("usage") or {},
                          model=saved.get("model", ""), cached=True)
        p = Perception.model_validate(fill_missing(copy.deepcopy(ans.data), SCHEMA))
    else:
        system, parts, model = build_parts(item, people, neighbours(item["taken_at"], item["sha256"]))
        ans = chat.ask(parts, system=system, model=model, schema=SCHEMA, schema_name="perception",
                       use_cache=not force)
        try:
            p = Perception.model_validate(fill_missing(copy.deepcopy(ans.data), SCHEMA))
        except ValidationError as err:
            fix = parts + [chat.text(f"Your previous JSON failed validation:\n{err}\nReturn corrected JSON only.")]
            ans = chat.ask(fix, system=system, model=model, schema=SCHEMA, schema_name="perception",
                           use_cache=False)
            p = Perception.model_validate(fill_missing(copy.deepcopy(ans.data), SCHEMA))
    p.media_id = item["sha256"]
    p, notes = review(p, {x["id"] for x in people}, item["kind"])
    notes += verify(item, p, people)

    effective = item["taken_at"]
    est = p.scene.date.estimate
    if item["date_source"] not in TRUSTED_DATES and est and p.scene.date.confidence >= 0.4:
        full = est if len(est) > 7 else (est + "-07-01" if len(est) == 4 else est + "-15")
        # an upload date is right for phone photos; replace it only when the content says
        # the photo is clearly older (a scan or an old print uploaded years later)
        if item["date_source"] != "upload" or full[:4] <= str(int(item["taken_at"][:4]) - 2):
            effective = full
    with WRITE_LOCK:
        stats = graph_write.write(item, p, notes, effective)
    OUT.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"raw": ans.data, "perception": p.model_dump(), "critic_notes": notes,
                               "model": ans.model,
                               "usage": ans.usage, "effective_date": effective},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    return {"path": item["path"], "seconds": round(time.perf_counter() - t0, 1), "model": ans.model,
            "cached": ans.cached, "notes": len(notes), **stats}


def pending(kind: str | None, limit: int | None) -> list[dict]:
    con = connect()
    q = "SELECT * FROM items WHERE dup_of IS NULL AND error IS NULL"
    args: list = []
    if kind:
        q += " AND kind=?"
        args.append(kind)
    rows = [dict(r) for r in con.execute(q + " ORDER BY taken_at", args)]
    return rows[:limit] if limit else rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--kind", choices=["photo", "video", "audio"])
    ap.add_argument("--force", action="store_true", help="ask Muse again")
    ap.add_argument("--redo", action="store_true", help="re-run critic + graph write from saved replies")
    a = ap.parse_args()
    rosters = {ds: roster(ds) for ds in ("demo", "real")}
    items = pending(a.kind, a.limit)
    print(f"{len(items)} items, known people: " + ", ".join(f"{k} {len(v)}" for k, v in rosters.items()), flush=True)
    done = failed = 0
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(perceive_item, it, rosters[dataset_of(it["path"])], a.force, a.redo): it
                for it in items}
        for f in as_completed(futs):
            try:
                r = f.result()
                done += 1
                print(json.dumps(r, ensure_ascii=False), flush=True)
            except Exception as e:  # noqa: BLE001 - one bad item must not stop the pass
                failed += 1
                print(f"FAIL {futs[f]['path']}: {type(e).__name__}: {str(e)[:300]}", flush=True)
    print(f"done {done}, failed {failed}")


if __name__ == "__main__":
    main()
