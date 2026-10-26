"""Muse Spark / Wonder / Spark Open calls with multimodal parts and JSON-schema output.

Callers build a list of `Part`s and get back an `Answer`. Text, image and audio
go through Chat Completions (works on Meta Model API and on Baseten). Video is
only documented for the Responses API, so any request with a video part is
sent there, with the clip uploaded through the Files API.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mlg.config import settings
from mlg.muse import cache
from mlg.muse.files import upload
from mlg.muse.http import MetaHTTP
from mlg.muse.media import audio_b64, image_data_url, sha256_file, to_mp4


@dataclass
class Part:
    kind: str                     # text | image | audio | video
    text: str = ""
    path: Path | None = None
    image_url: str | None = None  # prebuilt data URL (e.g. a contact sheet)

    def fingerprint(self) -> Any:
        if self.kind == "text":
            return ["text", self.text]
        if self.image_url:
            return [self.kind, cache.key_for(self.image_url)]
        return [self.kind, sha256_file(self.path)]


def text(t: str) -> Part:
    return Part("text", text=t)


def image(p: Path | str) -> Part:
    return Part("image", path=Path(p))


def image_url(url: str) -> Part:
    return Part("image", image_url=url)


def audio(p: Path | str) -> Part:
    return Part("audio", path=Path(p))


def video(p: Path | str) -> Part:
    return Part("video", path=Path(p))


@dataclass
class Answer:
    text: str
    data: Any = None
    usage: dict = field(default_factory=dict)
    model: str = ""
    seconds: float = 0.0
    cached: bool = False


@dataclass
class Provider:
    name: str
    http: MetaHTTP
    default_model: str

    @classmethod
    def meta(cls) -> "Provider":
        s = settings()
        return cls("meta", MetaHTTP(), s.model)

    @classmethod
    def baseten(cls) -> "Provider":
        s = settings()
        if not s.baseten_key:
            raise RuntimeError("BASETEN_API_KEY is empty")
        return cls("baseten", MetaHTTP(s.baseten_url, s.baseten_key), s.baseten_model)


def _chat_part(p: Part) -> dict:
    if p.kind == "text":
        return {"type": "text", "text": p.text}
    if p.kind == "image":
        return {"type": "image_url", "image_url": {"url": p.image_url or image_data_url(p.path)}}
    if p.kind == "audio":
        return {"type": "input_audio", "input_audio": {"data": audio_b64(p.path), "format": "wav"}}
    raise ValueError(f"{p.kind} parts go through the Responses API")


def _responses_part(p: Part, http: MetaHTTP) -> dict:
    if p.kind == "text":
        return {"type": "input_text", "text": p.text}
    if p.kind == "image":
        return {"type": "input_image", "image_url": p.image_url or image_data_url(p.path)}
    if p.kind == "audio":
        return {"type": "input_audio", "input_audio": {"data": audio_b64(p.path), "format": "wav"}}
    if p.kind == "video":
        return {"type": "input_video", "file_id": upload(to_mp4(p.path), http)}
    raise ValueError(p.kind)


def _json_from(text_out: str) -> Any:
    try:
        return json.loads(text_out)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text_out, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def _responses_text(body: dict) -> str:
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    chunks = []
    for item in body.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") in ("output_text", "text"):
                    chunks.append(c.get("text", ""))
    return "".join(chunks)


def ask(parts: list[Part], *, system: str | None = None, model: str | None = None,
        schema: dict | None = None, schema_name: str = "result", effort: str = "medium",
        max_tokens: int = 16000, provider: Provider | None = None, use_cache: bool = True,
        force_responses: bool = False) -> Answer:
    """One model call. With `schema`, the reply is parsed into `Answer.data`."""
    provider = provider or Provider.meta()
    model = model or provider.default_model
    use_responses = force_responses or any(p.kind == "video" for p in parts)
    key = cache.key_for({"p": provider.name, "m": model, "s": system, "schema": schema,
                         "e": effort, "r": use_responses, "parts": [p.fingerprint() for p in parts]})
    if use_cache and (hit := cache.get(key)):
        return Answer(**hit, cached=True)

    # Strict schema still yields malformed JSON now and then (seen in testing);
    # a fresh attempt nearly always fixes it, and bad replies are never cached.
    for attempt in range(3):
        try:
            answer = _call(parts, system, model, schema, schema_name, effort, max_tokens, provider, use_responses)
            break
        except json.JSONDecodeError:
            if attempt == 2:
                raise
    cache.put(key, {"text": answer.text, "data": answer.data, "usage": answer.usage,
                    "model": answer.model, "seconds": answer.seconds})
    return answer


def _call(parts, system, model, schema, schema_name, effort, max_tokens, provider, use_responses) -> Answer:
    if use_responses:
        body: dict[str, Any] = {
            "model": model,
            "input": [{"type": "message", "role": "user",
                       "content": [_responses_part(p, provider.http) for p in parts]}],
            "max_output_tokens": max_tokens,
            "reasoning": {"effort": effort},
        }
        if system:
            body["instructions"] = system
        if schema:
            body["text"] = {"format": {"type": "json_schema", "name": schema_name,
                                       "schema": schema, "strict": True}}
        reply = provider.http.post("/responses", body)
        out = _responses_text(reply.body)
    else:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": [_chat_part(p) for p in parts]})
        body = {"model": model, "messages": messages, "max_tokens": max_tokens,
                "reasoning_effort": effort}
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": schema_name, "schema": schema, "strict": True}}
        reply = provider.http.post("/chat/completions", body)
        msg = reply.body["choices"][0]["message"]
        content = msg.get("content")
        out = content if isinstance(content, str) else "".join(
            c.get("text", "") for c in (content or []) if isinstance(c, dict))

    answer = Answer(text=out, usage=reply.body.get("usage") or {}, model=model,
                    seconds=round(reply.seconds, 2))
    if schema:
        answer.data = _json_from(out)
    return answer
