"""What the Perceive pass must return for one media item, as Pydantic models.

`strict_schema()` turns the model into the strict JSON-schema subset the Meta
API enforces: no $ref, every object closed, every key required (optional
values are nullable instead of missing).
"""
from __future__ import annotations

import copy
from typing import Literal

from pydantic import BaseModel, Field

EMOTIONS = ("joy", "love", "pride", "gratitude", "excitement", "calm", "nostalgia", "surprise",
            "amusement", "sadness", "grief", "anxiety", "frustration", "anger", "boredom", "tenderness")
Emotion = Literal[EMOTIONS]  # type: ignore[valid-type]

EdgeType = Literal["INTERACTED_WITH", "FELT", "EVOKED_EMOTION", "PERFORMED", "FEATURES",
                   "RELATED_TO", "PRESENT_AT", "MENTIONS", "SAID"]
Basis = Literal["observed", "inferred"]
DateSource = Literal["exif", "container", "filename", "content", "speech", "unknown"]


class Evidence(BaseModel):
    bbox: list[int] | None = Field(None, description="[x1,y1,x2,y2] on the 0-1000 grid of the image/frame")
    t: list[float] | None = Field(None, description="[t0,t1] seconds in audio/video")
    frame: int | None = Field(None, description="index of the keyframe the bbox refers to, if several")
    cue: str = Field(description="the visible or audible cue, a few words")


class Setting(BaseModel):
    indoor: bool | None
    place_type: str
    place_name: str | None
    evidence: list[Evidence]
    confidence: float


class DateGuess(BaseModel):
    estimate: str | None = Field(description="YYYY, YYYY-MM or YYYY-MM-DD")
    source: DateSource
    rationale: str
    confidence: float


class EventGuess(BaseModel):
    type: str = Field(description="birthday|wedding|trip|meal|holiday|party|ceremony|sport|everyday|...")
    title: str
    rationale: str
    confidence: float


class Scene(BaseModel):
    summary: str = Field(description="at most 2 sentences")
    setting: Setting
    date: DateGuess
    event_guess: EventGuess


class PersonSeen(BaseModel):
    local_id: str = Field(description="p1, p2, ...")
    known_person_id: str | None = Field(description="id from KNOWN_PEOPLE, only with a stated match")
    name: str | None = Field(description="only if known or spoken/written in the media")
    match_rationale: str | None
    appearance: str = Field(description="age band, hair, clothing - enough to re-identify")
    role_in_scene: str
    expression: str
    bbox: list[int] | None
    frame: int | None
    confidence: float


class ObjectSeen(BaseModel):
    local_id: str
    name: str
    category: str
    salience: float
    bbox: list[int] | None
    confidence: float


class ActivitySeen(BaseModel):
    local_id: str
    name: str
    participants: list[str]
    confidence: float


class UtteranceHeard(BaseModel):
    local_id: str
    speaker: str = Field(description="local person id, or 'unknown'")
    text: str = Field(description="verbatim, original language")
    t: list[float] | None
    tone: str
    mentions: list[str]


class EdgeProps(BaseModel):
    kind: str | None
    valence: float | None = Field(description="-1..1")
    intensity: float | None = Field(description="0..1")
    role: str | None


class Edge(BaseModel):
    type: EdgeType
    source: str = Field(description="local id, or 'scene'")
    target: str = Field(description="local id, emotion name, or 'event'")
    props: EdgeProps
    basis: Basis
    evidence: list[Evidence]
    rationale: str = Field(description="one sentence tied to observable cues")
    confidence: float


class Perception(BaseModel):
    media_id: str
    scene: Scene
    people: list[PersonSeen]
    objects: list[ObjectSeen]
    activities: list[ActivitySeen]
    utterances: list[UtteranceHeard]
    edges: list[Edge]
    open_questions: list[str]


def _inline(node, defs):
    if isinstance(node, dict):
        if "$ref" in node:
            return _inline(copy.deepcopy(defs[node["$ref"].split("/")[-1]]), defs)
        out = {k: _inline(v, defs) for k, v in node.items() if k not in ("title", "default")}
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"])
        return out
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    return node


def strict_schema(model: type[BaseModel] = Perception) -> dict:
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})
    return _inline(raw, defs)
