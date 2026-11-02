"""Muse Spark / Wonder / Spark Open calls with multimodal parts and JSON-schema output.

Callers build a list of `Part`s and get back an `Answer`. Text, image and audio
go through Chat Completions (works on Meta Model API and on Baseten). Video is
only documented for the Responses API, so any request with a video part is
sent there, with the clip uploaded through the Files API.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from mlg.config import settings
from mlg.muse import cache
from mlg.muse.files import upload
from mlg.muse.http import MetaHTTP, MuseError
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
    provider: str = "meta"        # who served it: meta | baseten
    fallback: str = ""            # why a Spark Open call went to the API instead

    @property
    def served_by(self) -> str:
        return SERVED_BY.get(self.provider, self.provider)


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
    def local(cls) -> "Provider":
        """This computer's own model behind an OpenAI-compatible server (Ollama, LM Studio, llama.cpp)."""
        s = settings()
        if not s.local_model:
            raise RuntimeError("No local model chosen - pick one on the setup screen (MLG_LOCAL_MODEL)")
        return cls("local", MetaHTTP(s.local_url, "local", timeout=LOCAL_TIMEOUT, provider="local", tries=2),
                   s.local_model)

    @classmethod
    def baseten(cls) -> "Provider":
        s = settings()
        if not s.baseten_key:
            raise RuntimeError("BASETEN_API_KEY is empty")
        # Spark Open on Baseten sometimes takes minutes on pictures (measured: 4 of 15 scenes over 3 min);
        # a short leash and the API fallback (instead of a second try) keep a film moving
        return cls("baseten", MetaHTTP(s.baseten_url, s.baseten_key, timeout=OPEN_TIMEOUT, provider="baseten",
                                       tries=1), s.baseten_model)


# Work that runs on Muse Spark Open (Meta's open weights, served by Baseten) when a Baseten key is set.
# MLG_SPARK_OPEN lists the tasks ("all", "none", or e.g. "search,titles"); anything else stays on the
# Muse Spark API. A failed Spark Open call falls back to the API, and the log says so.
OPEN_TASKS = {"search", "titles", "circles", "checker"}
OPEN_TIMEOUT = float(os.environ.get("MLG_SPARK_OPEN_TIMEOUT", "60"))
LOCAL_TIMEOUT = float(os.environ.get("MLG_LOCAL_TIMEOUT", "900"))   # a consumer GPU can take minutes on a video
SERVED_BY = {"baseten": "Muse Spark Open on Baseten", "meta": "Muse Spark (Meta Model API)",
             "local": "this computer's own model"}


def open_tasks() -> set[str]:
    raw = os.environ.get("MLG_SPARK_OPEN", "default").strip().lower()
    if raw in ("none", "off", "0", ""):
        return set()
    if raw == "default":
        return OPEN_TASKS
    if raw == "all":
        return OPEN_TASKS | {"*"}
    return {t.strip() for t in raw.split(",") if t.strip()}


def provider_for(task: str | None, parts: list[Part] | None = None) -> Provider:
    mode = settings().mode
    # local: everything here; mixed: anything carrying a picture or a sound stays here, only text goes out
    if mode == "local" or (mode == "mixed" and any(p.kind != "text" for p in parts or [])):
        return Provider.local()
    tasks = open_tasks()
    if task and settings().baseten_key and (task in tasks or "*" in tasks):
        return Provider.baseten()
    return Provider.meta()


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
        force_responses: bool = False, task: str | None = None) -> Answer:
    """One model call. With `schema`, the reply is parsed into `Answer.data`.

    `task` names the job ("search", "titles", ...) for the usage log and picks the provider: tasks listed
    in MLG_SPARK_OPEN run on Muse Spark Open (Baseten) and fall back to the Muse Spark API if it fails."""
    provider = provider or provider_for(task, parts)
    if provider.name == "local":
        return _ask(local_parts(parts), system, provider.default_model, schema, schema_name, effort,
                    max_tokens, provider, use_cache, False, task)
    use_responses = force_responses or any(p.kind == "video" for p in parts)
    if provider.name == "baseten":
        if use_responses:
            provider = Provider.meta()              # Spark Open is served through Chat Completions only
        else:
            model = provider.default_model
            max_tokens = max(max_tokens, 4000)      # it reasons first (~600 tokens) and answers after
    model = model or provider.default_model
    try:
        return _ask(parts, system, model, schema, schema_name, effort, max_tokens, provider, use_cache,
                    use_responses, task)
    except (MuseError, json.JSONDecodeError, httpx.HTTPError) as e:
        if provider.name != "baseten":
            raise
        meta = Provider.meta()
        answer = _ask(parts, system, meta.default_model, schema, schema_name, effort, max_tokens, meta,
                      use_cache, use_responses, task)
        answer.fallback = f"{type(e).__name__}: {str(e)[:160]}"
        return answer


def local_parts(parts: list[Part]) -> list[Part]:
    """What a local model can take: text and pictures. A video becomes its keyframes; a sound becomes its
    words, heard on this computer by Whisper - or a note that it was left out. Nothing goes to the cloud."""
    out: list[Part] = []
    for p in parts:
        if p.kind == "video":
            from mlg.perceive.keyframes import keyframes
            frames = keyframes(p.path)
            out.append(text(f"(the video as {len(frames)} keyframes in order)"))
            for t, f in frames:
                out += [text(f"at {t:.1f} s"), image(f)]
        elif p.kind == "audio":
            from mlg.muse import local_asr
            if local_asr.available():
                segs = local_asr.segments(p.path)
                out.append(text("(the sound, transcribed on this computer)\n" + ("\n".join(
                    f"[{a:.1f}-{b:.1f}] {w}" for a, b, w in segs) or "(no speech)")))
            else:
                out.append(text("(there is sound here, but this computer has no speech model; it was left out)"))
        else:
            out.append(p)
    return out


def _ask(parts, system, model, schema, schema_name, effort, max_tokens, provider, use_cache, use_responses,
         task) -> Answer:
    key = cache.key_for({"p": provider.name, "m": model, "s": system, "schema": schema,
                         "e": effort, "r": use_responses, "parts": [p.fingerprint() for p in parts]})
    if use_cache and (hit := cache.get(key)):
        return Answer(**{"provider": provider.name, **hit}, cached=True)

    # Strict schema still yields malformed JSON now and then (seen in testing);
    # a fresh attempt nearly always fixes it, and bad replies are never cached.
    for attempt in range(3):
        try:
            answer = _call(parts, system, model, schema, schema_name, effort, max_tokens, provider,
                           use_responses, task)
            break
        except json.JSONDecodeError:
            if attempt == 2:
                raise
    cache.put(key, {"text": answer.text, "data": answer.data, "usage": answer.usage,
                    "model": answer.model, "seconds": answer.seconds, "provider": provider.name})
    return answer


def _call(parts, system, model, schema, schema_name, effort, max_tokens, provider, use_responses,
          task=None) -> Answer:
    log = {"task": task} if task else None
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
        reply = provider.http.post("/responses", body, log)
        out = _responses_text(reply.body)
    else:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": [_chat_part(p) for p in parts]})
        body = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if provider.name != "local":           # local servers don't all know it; some reject the request
            body["reasoning_effort"] = effort
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": schema_name, "schema": schema, "strict": True}}
        try:
            reply = provider.http.post("/chat/completions", body, log)
        except MuseError as e:
            if provider.name != "local" or e.status != 400 or not schema:
                raise
            # an older local server without structured output: ask for JSON and describe the shape instead
            messages[0:0] = [{"role": "system", "content": "Answer with JSON only, matching this JSON schema:\n"
                              + json.dumps(schema)}]
            body["response_format"] = {"type": "json_object"}
            reply = provider.http.post("/chat/completions", body, log)
        msg = reply.body["choices"][0]["message"]
        content = msg.get("content")
        out = content if isinstance(content, str) else "".join(
            c.get("text", "") for c in (content or []) if isinstance(c, dict))

    if provider.name == "baseten" and not out.strip():
        raise MuseError(reply.status, {"error": {"message": "empty answer (reasoning used every token)"}},
                        "/chat/completions")
    answer = Answer(text=out, usage=reply.body.get("usage") or {}, model=model,
                    seconds=round(reply.seconds, 2), provider=provider.name)
    if schema:
        answer.data = _json_from(out)
    return answer
