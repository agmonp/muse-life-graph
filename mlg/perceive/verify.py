"""Second key for identity: verify every roster match on the face crop alone.

The Perceive call sees the whole scene plus album names and captions, and it
tends to over-claim ("childhood album + curly hair -> the owner"). Here a
separate Muse call gets ONLY the reference crop and the candidate crop - no
album, no caption, no neighbours - and must decide same / different / unsure.
Only a confident "same" keeps the name; everything else becomes an open
question for the human.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from mlg.muse import chat
from mlg.muse.media import image_data_url, open_image
from mlg.perceive.keyframes import keyframes
from mlg.perceive.schema import Perception

MIN_CONF = 0.75
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["verdict", "confidence", "age_gap_years", "reason"],
    "properties": {
        "verdict": {"type": "string", "enum": ["same", "different", "unsure"]},
        "confidence": {"type": "number"},
        "age_gap_years": {"type": "integer", "description": "rough age difference between the two crops"},
        "reason": {"type": "string", "description": "facial features compared, one sentence"},
    },
}
SYSTEM = (
    "You verify identity for a family photo archive. You get two crops: A is a reference photo of a "
    "known person, B is a person found in another photo. Decide whether B is the same person as A "
    "using FACIAL features only (face shape, eyes, nose, mouth, ears, hairline). Hair style, clothes, "
    "glasses and setting are weak cues. If the faces differ a lot in age (e.g. a child vs an adult), "
    "if B's face is small, blurred, turned away or covered, answer 'unsure' - never 'same'. Being "
    "wrong with a 'same' is much worse than saying 'unsure'."
)


def _crop(item: dict, bbox: list[int], frame: int | None) -> Image.Image | None:
    path = Path(item["path"])
    if item["kind"] == "video":
        frames = keyframes(path)
        if not frames:
            return None
        img = open_image(frames[min(frame or 0, len(frames) - 1)][1])
    elif item["kind"] == "photo":
        img = open_image(path)
    else:
        return None
    w, h = img.size
    x1, y1, x2, y2 = (bbox + [0, 0, 1000, 1000])[:4]
    x1, x2 = sorted((x1 * w / 1000, x2 * w / 1000))
    y1, y2 = sorted((y1 * h / 1000, y2 * h / 1000))
    mx, my = (x2 - x1) * 0.1, (y2 - y1) * 0.1
    box = (max(0, x1 - mx), max(0, y1 - my), min(w, x2 + mx), min(h, y1 + (y2 - y1) * 0.65 + my))
    if box[2] - box[0] < 24 or box[3] - box[1] < 24:
        return None
    crop = img.crop(tuple(int(v) for v in box))
    crop.thumbnail((512, 512))
    return crop


def verify(item: dict, p: Perception, people: list[dict]) -> list[str]:
    """Mutates p: unverified matches lose their known_person_id. Returns notes."""
    refs = {x["id"]: x for x in people}
    notes = []
    for person in p.people:
        pid = person.known_person_id
        if not pid:
            continue
        ref = refs.get(pid)
        crop = _crop(item, person.bbox, person.frame) if person.bbox else None
        if not ref or not ref.get("crop") or crop is None:
            verdict = {"verdict": "unsure", "confidence": 0.0, "reason": "no usable face crop"}
        else:
            ans = chat.ask([chat.text(f"A = reference photo of {ref['name']}:"), chat.image(ref["crop"]),
                            chat.text("B = the person to check:"), chat.image_url(image_data_url(crop, 512))],
                           system=SYSTEM, schema=SCHEMA, schema_name="identity_check", effort="low",
                           max_tokens=4000)
            verdict = ans.data
        ok = verdict.get("verdict") == "same" and float(verdict.get("confidence") or 0) >= MIN_CONF
        person.match_rationale = (f"{person.match_rationale or ''} | verify: {verdict.get('verdict')} "
                                  f"{float(verdict.get('confidence') or 0):.2f} - {verdict.get('reason', '')}")
        if not ok:
            notes.append(f"{person.local_id}: {pid} not confirmed by face check "
                         f"({verdict.get('verdict')}) - name removed")
            p.open_questions.append(f"Is {person.local_id} ({person.appearance[:60]}) {ref['name'] if ref else pid}?")
            person.known_person_id = None
            person.name = None
    return notes
