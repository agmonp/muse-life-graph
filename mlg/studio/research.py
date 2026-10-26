"""The Researcher: everything the film crew may use, pulled from the life graph.

Returns moments (one per media item) with who is in them, what they felt, what
was said, and where each named person's face is - so later stages can frame
shots on the right face and quote the right words. Nothing here is invented:
the screenwriter may only build scenes from these moment ids.
"""
from __future__ import annotations

from mlg.graph.db import session
from mlg.people import dataset_of


def moments(dataset: str = "demo", person_ids: list[str] | None = None) -> list[dict]:
    with session() as s:
        rows = s.run("""
            MATCH (m:Moment)-[:DEPICTED_IN]->(mi:MediaItem)
            OPTIONAL MATCH (p:Person)-[:OBSERVED_AS]->(o:Observation)-[:PRESENT_AT]->(m)
            WITH m, mi, collect(DISTINCT {id: p.id, name: p.name, bbox: o.bbox, frame: o.frame,
                                         expression: o.expression}) AS faces
            OPTIONAL MATCH (m)-[ev:EVOKED_EMOTION]->(e:Emotion)
            WITH m, mi, faces, collect(DISTINCT {emotion: e.name, intensity: ev.intensity}) AS mood
            OPTIONAL MATCH (u:Utterance)-[:IN]->(mi)
            OPTIONAL MATCH (sp:Person)-[:OBSERVED_AS]->(:Observation)-[:SAID]->(u)
            WITH m, mi, faces, mood, collect(DISTINCT {id: u.id, text: u.text, text_en: u.text_en, t0: u.t0,
                                                       t1: u.t1, tone: u.tone,
                                                       speaker: coalesce(sp.name, u.speaker_name)}) AS said
            OPTIONAL MATCH (m)-[:FEATURES]->(ob:Object)
            RETURN m.id AS id, m.start AS date, m.date_source AS date_source, m.summary AS summary,
                   m.event_type AS event_type, m.event_title AS event, m.place_type AS place,
                   mi.id AS sha, mi.path AS path, mi.kind AS kind, mi.duration_s AS duration,
                   mi.width AS width, mi.height AS height, faces, mood, said,
                   collect(DISTINCT ob.name)[..6] AS objects
            ORDER BY m.start""").data()
    out = []
    for r in rows:
        if dataset_of(r["path"]) != dataset:
            continue
        r["faces"] = [f for f in r["faces"] if f.get("id")]
        r["people"] = sorted({f["name"] for f in r["faces"]})
        r["mood"] = [x for x in r["mood"] if x.get("emotion")]
        r["said"] = [x for x in r["said"] if x.get("id") and x.get("text")]
        if person_ids and not ({f["id"] for f in r["faces"]} & set(person_ids)) and not r["said"]:
            continue
        out.append(r)
    return out


def for_prompt(ms: list[dict]) -> list[dict]:
    """Compact view of moments for the screenwriter (no paths, no boxes)."""
    return [{"id": m["id"], "date": (m["date"] or "")[:10], "kind": m["kind"],
             "duration_s": round(m["duration"], 1) if m["duration"] else None,
             "event": m["event"], "summary": m["summary"], "people": m["people"],
             "mood": [f"{x['emotion']} {x.get('intensity') or ''}".strip() for x in m["mood"]],
             "objects": m["objects"],
             "voice_lines": [{"id": u["id"], "speaker": u["speaker"], "text": u["text"][:220],
                              **({"english": u["text_en"][:220]} if u.get("text_en") and u["text_en"] != u["text"]
                                 else {}),
                              "seconds": round((u["t1"] or 0) - (u["t0"] or 0), 1)} for u in m["said"]]}
            for m in ms]
