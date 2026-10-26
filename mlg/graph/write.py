"""Write one media item's Perception into Neo4j, idempotently.

Everything derived from an item has an id prefixed with its sha256
("<sha>:p1", "<sha>:moment"), so re-perceiving deletes and rebuilds exactly
that item's sub-graph. Shared nodes (Person, Emotion, Location, Topic) are
MERGEd and never deleted here.

People are written as Observations (one person in one item). Only roster
matches get a Person-[:OBSERVED_AS]->Observation link; unknown people are
resolved into Persons later by the identity pass.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict

from mlg.graph.db import session
from mlg.perceive.schema import EMOTIONS, Perception


def _slug(s: str) -> str:
    return re.sub(r"[^\w]+", "-", s.strip().lower()).strip("-")


def _ev(evidence) -> str:
    return json.dumps([e.model_dump(exclude_none=True) for e in evidence], ensure_ascii=False)


def _endpoint(sha: str, ref: str, labels: dict[str, str]) -> tuple[str, dict] | None:
    """(label, match-props) for an edge endpoint written by this item."""
    if ref in ("scene", "event"):
        return "Moment", {"id": f"{sha}:moment"}
    if ref in labels:
        return labels[ref], {"id": f"{sha}:{ref}"}
    if ref.lower() in EMOTIONS:
        return "Emotion", {"name": ref.lower()}
    return None


def write(item: dict, p: Perception, notes: list[str], effective_date: str,
          candidates: dict[str, dict] | None = None, user_actions: dict[str, str] | None = None) -> dict:
    sha = item["sha256"]
    labels = ({x.local_id: "Observation" for x in p.people} | {x.local_id: "Object" for x in p.objects}
              | {x.local_id: "Activity" for x in p.activities} | {x.local_id: "Utterance" for x in p.utterances})
    edges_by_shape: dict[tuple, list[dict]] = defaultdict(list)
    topics = []
    for e in p.edges:
        src = _endpoint(sha, e.source, labels)
        tgt = _endpoint(sha, e.target, labels)
        if e.type == "MENTIONS" and src and tgt is None:
            topics.append({"src": src[1]["id"], "name": e.target.strip().lower()[:80]})
            continue
        if not src or not tgt:
            continue
        edges_by_shape[(e.type, src[0], tgt[0], "name" if "name" in tgt[1] else "id")].append({
            "src": src[1]["id"], "tgt": next(iter(tgt[1].values())),
            "props": {"confidence": e.confidence, "basis": e.basis, "rationale": e.rationale,
                      "evidence": _ev(e.evidence), "inferred_by": "perceive",
                      **{k: v for k, v in e.props.model_dump().items() if v is not None}},
        })

    with session() as s:
        s.execute_write(_write_tx, sha, item, p, notes, effective_date, edges_by_shape, topics,
                        candidates or {}, user_actions or {})
    return {"people": len(p.people), "edges": sum(len(v) for v in edges_by_shape.values()),
            "known": sum(1 for x in p.people if x.known_person_id)}


def _write_tx(tx, sha, item, p: Perception, notes, effective_date, edges_by_shape, topics,
              candidates, user_actions):
    sc = p.scene
    tx.run("""MERGE (mi:MediaItem {id: $sha})
              SET mi.path = $path, mi.kind = $kind, mi.taken_at = $taken_at, mi.date_source = $date_source,
                  mi.effective_date = $eff, mi.width = $w, mi.height = $h, mi.duration_s = $dur""",
           sha=sha, path=item["path"], kind=item["kind"], taken_at=item["taken_at"],
           date_source=item["date_source"], eff=effective_date, w=item.get("width"), h=item.get("height"),
           dur=item.get("duration_s")).consume()
    tx.run("MATCH (n) WHERE n.id STARTS WITH $prefix DETACH DELETE n", prefix=f"{sha}:").consume()
    tx.run("""MATCH (mi:MediaItem {id: $sha})
              CREATE (m:Moment {id: $id, summary: $summary, start: $start, indoor: $indoor,
                                place_type: $place_type, event_type: $etype, event_title: $etitle,
                                event_confidence: $econf, event_rationale: $erat, date_estimate: $dest,
                                date_source: $dsrc, date_rationale: $drat, open_questions: $oq,
                                critic_notes: $notes})
              CREATE (m)-[:DEPICTED_IN]->(mi)""",
           sha=sha, id=f"{sha}:moment", summary=sc.summary, start=effective_date, indoor=sc.setting.indoor,
           place_type=sc.setting.place_type, etype=sc.event_guess.type, etitle=sc.event_guess.title,
           econf=sc.event_guess.confidence, erat=sc.event_guess.rationale, dest=sc.date.estimate,
           dsrc=sc.date.source, drat=sc.date.rationale, oq=p.open_questions, notes=notes).consume()
    if sc.setting.place_name:
        tx.run("""MATCH (m:Moment {id: $mid})
                  MERGE (l:Location {id: $lid}) ON CREATE SET l.name = $name, l.kind = $kind
                  CREATE (m)-[:OCCURRED_AT {confidence: $conf, evidence: $ev}]->(l)""",
               mid=f"{sha}:moment", lid=f"loc:{_slug(sc.setting.place_name)}", name=sc.setting.place_name,
               kind=sc.setting.place_type, conf=sc.setting.confidence, ev=_ev(sc.setting.evidence)).consume()

    tx.run("""MATCH (mi:MediaItem {id: $sha}), (m:Moment {id: $mid})
              UNWIND $people AS x
              CREATE (o:Observation {id: x.id, appearance: x.appearance, role: x.role, expression: x.expression,
                                     bbox: x.bbox, frame: x.frame, confidence: x.confidence, name_hint: x.name,
                                     candidate: x.cand, candidate_verdict: x.cand_verdict,
                                     candidate_conf: x.cand_conf, candidate_reason: x.cand_reason,
                                     user_action: x.user_action})
              CREATE (o)-[:IN]->(mi)
              CREATE (o)-[:PRESENT_AT {role: x.role, confidence: x.confidence}]->(m)
              WITH o, x WHERE x.known IS NOT NULL
              MATCH (person:Person {id: x.known})
              CREATE (person)-[:OBSERVED_AS {confidence: x.confidence, rationale: x.why}]->(o)""",
           sha=sha, mid=f"{sha}:moment",
           people=[{"id": f"{sha}:{x.local_id}", "appearance": x.appearance, "role": x.role_in_scene,
                    "expression": x.expression, "bbox": x.bbox, "frame": x.frame, "confidence": x.confidence,
                    "name": x.name, "known": x.known_person_id, "why": x.match_rationale,
                    "cand": candidates.get(x.local_id, {}).get("person"),
                    "cand_verdict": candidates.get(x.local_id, {}).get("verdict"),
                    "cand_conf": candidates.get(x.local_id, {}).get("conf"),
                    "cand_reason": candidates.get(x.local_id, {}).get("reason"),
                    "user_action": user_actions.get(x.local_id)} for x in p.people]).consume()
    tx.run("""MATCH (m:Moment {id: $mid})
              UNWIND $objs AS x
              CREATE (ob:Object {id: x.id, name: x.name, category: x.category, bbox: x.bbox})
              CREATE (m)-[:FEATURES {salience: x.salience, confidence: x.confidence}]->(ob)""",
           mid=f"{sha}:moment",
           objs=[{"id": f"{sha}:{x.local_id}", "name": x.name, "category": x.category, "bbox": x.bbox,
                  "salience": x.salience, "confidence": x.confidence} for x in p.objects]).consume()
    tx.run("""MATCH (m:Moment {id: $mid})
              UNWIND $acts AS x
              CREATE (a:Activity {id: x.id, name: x.name, confidence: x.confidence})
              CREATE (m)-[:INCLUDES]->(a)
              WITH a, x UNWIND x.who AS w
              MATCH (o:Observation {id: w})
              MERGE (o)-[:PERFORMED]->(a)""",
           mid=f"{sha}:moment",
           acts=[{"id": f"{sha}:{x.local_id}", "name": x.name, "confidence": x.confidence,
                  "who": [f"{sha}:{w}" for w in x.participants if w.startswith("p")]} for x in p.activities]).consume()
    tx.run("""MATCH (mi:MediaItem {id: $sha})
              UNWIND $utts AS x
              CREATE (u:Utterance {id: x.id, text: x.text, t0: x.t0, t1: x.t1, tone: x.tone})
              CREATE (u)-[:IN]->(mi)
              WITH u, x WHERE x.speaker IS NOT NULL
              MATCH (o:Observation {id: x.speaker})
              CREATE (o)-[:SAID]->(u)""",
           sha=sha,
           utts=[{"id": f"{sha}:{x.local_id}", "text": x.text, "tone": x.tone,
                  "t0": x.t[0] if x.t else None, "t1": x.t[1] if x.t and len(x.t) > 1 else None,
                  "speaker": f"{sha}:{x.speaker}" if x.speaker and x.speaker != "unknown" else None}
                 for x in p.utterances]).consume()

    # MERGE: the writer already made PRESENT_AT/PERFORMED/SAID links, and the model may
    # repeat an edge; one relationship per (type, source, target) keeps counts honest.
    for (rtype, slabel, tlabel, tkey), rows in edges_by_shape.items():
        tx.run(f"""UNWIND $rows AS r
                   MATCH (a:{slabel} {{id: r.src}}), (b:{tlabel} {{{tkey}: r.tgt}})
                   MERGE (a)-[rel:{rtype}]->(b) SET rel += r.props""", rows=rows).consume()
    if topics:
        tx.run("""UNWIND $rows AS r
                  MATCH (a {id: r.src}) MERGE (t:Topic {name: r.name}) CREATE (a)-[:MENTIONS]->(t)""",
               rows=topics).consume()
