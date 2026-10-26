"""Muse Voice Transcribe (file endpoint): Hebrew/English speech with speaker turns.

Limits from the docs: mono 16-bit WAV at 16/24 kHz, 10 minutes, 32 MB per call.
Longer recordings are cut into 9-minute windows and the turns re-timed.
Speaker labels (A, B, ...) are per call, not identities.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from mlg.config import settings
from mlg.muse import cache
from mlg.muse.http import MetaHTTP
from mlg.muse.media import probe_duration, sha256_file, to_wav

WINDOW_S = 540


@dataclass
class Turn:
    start_ms: int
    end_ms: int
    text: str
    speaker: str | None = None
    window: int = 0


@dataclass
class Transcript:
    text: str
    duration_ms: int
    turns: list[Turn] = field(default_factory=list)

    def as_lines(self) -> str:
        return "\n".join(f"[{t.start_ms / 1000:.1f}-{t.end_ms / 1000:.1f}] "
                         f"{(t.speaker or '?')}{t.window}: {t.text}" for t in self.turns)


def _call(wav: Path, mode: str, languages: list[str] | None, keywords: list[str] | None,
          http: MetaHTTP) -> dict:
    req: dict = {"model": settings().transcribe_model, "audioEncoding": "WAV", "mode": mode}
    if languages:
        req["languageBias"] = languages
    if keywords:
        req["keywords"] = keywords
    with wav.open("rb") as f:
        reply = http.request("POST", "/asr/transcribe", files={
            "request": (None, json.dumps(req), "application/json"),
            "audio": (wav.name, f, "audio/wav"),
        })
    return reply.body


def transcribe(src: Path, *, mode: str = "DIARIZATION", languages: list[str] | None = None,
               keywords: list[str] | None = None, use_cache: bool = True) -> Transcript:
    http = MetaHTTP()
    key = cache.key_for({"asr": sha256_file(src), "mode": mode, "lang": languages, "kw": keywords})
    if use_cache and (hit := cache.get(key)):
        return Transcript(hit["text"], hit["duration_ms"], [Turn(**t) for t in hit["turns"]])

    total = probe_duration(src) or 0
    starts = [0.0] if total <= WINDOW_S + 30 else [i * WINDOW_S for i in range(int(total // WINDOW_S) + 1)]
    texts, turns, dur = [], [], 0
    for w, start in enumerate(starts):
        wav = to_wav(src, 16000, start if len(starts) > 1 else None,
                     WINDOW_S if len(starts) > 1 else None)
        body = _call(wav, mode, languages, keywords, http)
        offset = int(start * 1000)
        texts.append(body.get("transcript", ""))
        dur = offset + int(body.get("audioDurationMs", 0))
        for t in body.get("turns", []):
            turns.append(Turn(t["startMs"] + offset, t["endMs"] + offset,
                              t.get("transcript", ""), t.get("speaker"), w))
    result = Transcript(" ".join(x for x in texts if x), dur, turns)
    cache.put(key, {"text": result.text, "duration_ms": result.duration_ms,
                    "turns": [t.__dict__ for t in result.turns]})
    return result
