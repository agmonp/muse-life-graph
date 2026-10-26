"""Second key for identity: verify every roster match on the face crop alone.

The Perceive call sees the whole scene plus album names and captions, and it
tends to over-claim ("childhood album + curly hair -> the owner"). Here a
separate Muse call gets ONLY the person's reference crops and the candidate
crop - no album, no caption, no neighbours - and must decide same / different /
unsure. Only a confident "same" keeps the name; everything else becomes an open
question for the human, with the candidate kept for the "Who is this?" screen.
"""
from __future__ import annotations

from mlg.muse import chat
from mlg.muse.media import image_data_url
from mlg.perceive.crops import person_crop
from mlg.perceive.schema import Perception

MIN_CONF = 0.75
MAX_REFS = 3
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["verdict", "confidence", "age_gap_years", "reason"],
    "properties": {
        "verdict": {"type": "string", "enum": ["same", "different", "unsure"]},
        "confidence": {"type": "number"},
        "age_gap_years": {"type": "integer", "description": "rough age difference between A and B"},
        "reason": {"type": "string", "description": "facial features compared, one sentence"},
    },
}
SYSTEM = (
    "You verify identity for a family photo archive. You get one or more reference photos (A) of a "
    "known person and one crop (B) of a person found in another photo. Decide whether B is the same "
    "person as A using FACIAL features only (face shape, eyes, nose, mouth, ears, hairline). Hair "
    "style, clothes, glasses and setting are weak cues. If B's face is small, blurred, turned away or "
    "covered, or B is a child and no reference shows that person as a child, answer 'unsure' - never "
    "'same'. Being wrong with a 'same' is much worse than saying 'unsure'."
)


def check(ref: dict, crop) -> dict:
    refs = ref.get("crops") or ([ref["crop"]] if ref.get("crop") else [])
    if not refs or crop is None:
        return {"verdict": "unsure", "confidence": 0.0, "reason": "no usable face crop"}
    parts = []
    for i, c in enumerate(refs[:MAX_REFS]):
        parts += [chat.text(f"A{i + 1} = reference photo of {ref['name']}:"), chat.image(c)]
    parts += [chat.text("B = the person to check:"), chat.image_url(image_data_url(crop, 512))]
    return chat.ask(parts, system=SYSTEM, schema=SCHEMA, schema_name="identity_check", effort="low",
                    max_tokens=4000).data


IDENTIFY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["person_id", "confidence", "reason"],
    "properties": {
        "person_id": {"type": "string", "description": "an id from the list, or 'none'"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
}


def identify(crop, people: list[dict]) -> dict:
    """Which known person (if any) is this face? One call against all reference crops."""
    known = [p for p in people if p.get("crops")][:12]
    if crop is None or not known:
        return {"person_id": "none", "confidence": 0.0, "reason": "nothing to compare"}
    parts = [chat.text("Known people, with reference photos:")]
    for p in known:
        parts.append(chat.text(f"{p['id']} = {p['name']}"))
        parts += [chat.image(c) for c in p["crops"][:2]]
    parts += [chat.text("B = the person to identify:"), chat.image_url(image_data_url(crop, 512)),
              chat.text("Return the id of the known person B is, or 'none'.")]
    return chat.ask(parts, system=SYSTEM.replace("one or more reference photos (A) of a known person",
                                                 "reference photos of several known people"),
                    schema=IDENTIFY_SCHEMA, schema_name="identify", effort="low", max_tokens=4000).data


def verify(item: dict, p: Perception, people: list[dict]) -> tuple[list[str], dict[str, dict]]:
    """Mutates p: unverified matches lose their known_person_id.

    Returns (notes, candidates) where candidates maps local id -> the roster person the
    perceive pass proposed and the face check's verdict, for the human to settle.
    """
    refs = {x["id"]: x for x in people}
    notes, candidates = [], {}
    for person in p.people:
        pid = person.known_person_id
        if not pid:
            continue
        ref = refs.get(pid)
        crop = person_crop(item["path"], item["kind"], person.bbox, person.frame)
        verdict = check(ref, crop) if ref else {"verdict": "unsure", "confidence": 0.0, "reason": "not in roster"}
        conf = float(verdict.get("confidence") or 0)
        candidates[person.local_id] = {"person": pid, "verdict": verdict.get("verdict"), "conf": conf,
                                       "reason": verdict.get("reason", "")}
        person.match_rationale = (f"{person.match_rationale or ''} | verify: {verdict.get('verdict')} "
                                  f"{conf:.2f} - {verdict.get('reason', '')}")
        if not (verdict.get("verdict") == "same" and conf >= MIN_CONF):
            notes.append(f"{person.local_id}: {pid} not confirmed by face check "
                         f"({verdict.get('verdict')}) - name removed")
            p.open_questions.append(f"Is {person.local_id} ({person.appearance[:60]}) "
                                    f"{ref['name'] if ref else pid}?")
            person.known_person_id = None
            person.name = None
    return notes, candidates
