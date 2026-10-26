"""Rule-based critic for one Perception: enforce the prompt's rules in code.

Every change is recorded in `notes` so the Edit Room can show what was
dropped or downgraded and why. A model-based critic comes later; these rules
are the floor it can never go below.
"""
from __future__ import annotations

from mlg.perceive.schema import EMOTIONS, Perception

MIN_PERSON_CONF = 0.3
MAX_INFERRED = 0.8
MAX_RELATED = 0.7
MAX_VOICE_ID = 0.7
SPECIAL = {"scene", "event"}


def _clamp(x: float | None) -> float:
    return max(0.0, min(1.0, float(x or 0.0)))


def review(p: Perception, known_ids: set[str], kind: str = "photo") -> tuple[Perception, list[str]]:
    notes: list[str] = []
    spoken = " ".join(u.text for u in p.utterances).lower()

    keep_people = []
    for person in p.people:
        person.confidence = _clamp(person.confidence)
        if kind == "audio" and person.known_person_id and person.confidence > MAX_VOICE_ID:
            # no face to compare: a name from audio is reasoning from context, not recognition
            notes.append(f"{person.local_id}: voice-only identity {person.known_person_id} "
                         f"capped at {MAX_VOICE_ID}")
            person.confidence = MAX_VOICE_ID
            p.open_questions.append(f"Is the voice of {person.local_id} ({person.role_in_scene}) "
                                    f"really {person.known_person_id}?")
        if person.known_person_id and person.known_person_id not in known_ids:
            notes.append(f"{person.local_id}: unknown roster id {person.known_person_id!r} removed")
            person.known_person_id = None
        if person.name and not person.known_person_id and person.name.lower() not in spoken:
            notes.append(f"{person.local_id}: name {person.name!r} not known or spoken - removed")
            person.name = None
        if person.confidence < MIN_PERSON_CONF:
            notes.append(f"{person.local_id}: confidence {person.confidence:.2f} too low - dropped")
            continue
        keep_people.append(person)
    p.people = keep_people

    local = ({x.local_id for x in p.people} | {x.local_id for x in p.objects}
             | {x.local_id for x in p.activities} | {x.local_id for x in p.utterances})
    for act in p.activities:
        act.participants = [x for x in act.participants if x in local]

    keep_edges = []
    for e in p.edges:
        tag = f"{e.type} {e.source}->{e.target}"
        e.evidence = [ev for ev in e.evidence if ev.cue and ev.cue.strip()]
        if not e.evidence:
            notes.append(f"{tag}: no evidence - dropped")
            continue
        if e.type in ("FELT", "EVOKED_EMOTION"):
            e.target = e.target.lower().strip()
            if e.target not in EMOTIONS:
                notes.append(f"{tag}: emotion outside taxonomy - dropped")
                continue
        if e.source not in local | SPECIAL:
            notes.append(f"{tag}: unknown source - dropped")
            continue
        if e.type in ("INTERACTED_WITH", "RELATED_TO", "PERFORMED", "SAID") and e.target not in local:
            notes.append(f"{tag}: unknown target - dropped")
            continue
        conf = _clamp(e.confidence)
        cap = MAX_RELATED if e.type == "RELATED_TO" else (MAX_INFERRED if e.basis == "inferred" else 1.0)
        if conf > cap:
            notes.append(f"{tag}: confidence {conf:.2f} capped at {cap}")
            conf = cap
        e.confidence = conf
        keep_edges.append(e)
    p.edges = keep_edges
    return p, notes
