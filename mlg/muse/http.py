"""One HTTP client for every Meta Model API call: auth, retries, usage log.

Retry policy follows the API docs: retry 429/500/503 with backoff (honour
Retry-After), never retry 400/401/402/403/404/413, and treat 504 as "make the
request smaller or stream it" rather than retrying blindly.
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from typing import Any

import httpx

from mlg.config import CACHE, settings

RETRY_STATUS = {429, 500, 503}
MAX_TRIES = 6
USAGE_LOG = CACHE / "usage.jsonl"


class MuseError(RuntimeError):
    def __init__(self, status: int, body: Any, path: str):
        self.status, self.body, self.path = status, body, path
        err = body.get("error", {}) if isinstance(body, dict) else {}
        self.code = err.get("code")
        msg = err.get("message") or (body if isinstance(body, str) else json.dumps(body)[:500])
        super().__init__(f"{path} -> HTTP {status} {self.code or ''}: {msg}")


@dataclass
class Reply:
    status: int
    body: Any
    headers: httpx.Headers
    seconds: float


def _log_usage(path: str, model: str | None, body: Any, seconds: float) -> None:
    usage = body.get("usage") if isinstance(body, dict) else None
    USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with USAGE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "path": path, "model": model,
                            "seconds": round(seconds, 2), "usage": usage}) + "\n")


class MetaHTTP:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: float = 600):
        s = settings()
        self.base_url = (base_url or s.base_url).rstrip("/")
        self._key = api_key
        self.timeout = timeout

    def _headers(self, accept: str = "application/json") -> dict[str, str]:
        key = self._key or settings().require_key()
        return {"Authorization": f"Bearer {key}", "Accept": accept}

    def request(self, method: str, path: str, *, json_body: dict | None = None,
                files: dict | None = None, data: dict | None = None,
                accept: str = "application/json") -> Reply:
        url = f"{self.base_url}{path}"
        model = (json_body or {}).get("model")
        delay = 0.5
        for attempt in range(1, MAX_TRIES + 1):
            t0 = time.perf_counter()
            try:
                with httpx.Client(timeout=self.timeout) as c:
                    r = c.request(method, url, headers=self._headers(accept),
                                  json=json_body, files=files, data=data)
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError):
                if attempt == MAX_TRIES:
                    raise
                time.sleep(delay + random.random() * delay)
                delay *= 2
                continue
            seconds = time.perf_counter() - t0
            try:
                body: Any = r.json()
            except ValueError:
                body = r.text
            if r.status_code < 400:
                _log_usage(path, model, body, seconds)
                return Reply(r.status_code, body, r.headers, seconds)
            if r.status_code in RETRY_STATUS and attempt < MAX_TRIES:
                wait = r.headers.get("Retry-After")
                time.sleep(float(wait) if wait else delay + random.random() * delay)
                delay *= 2
                continue
            raise MuseError(r.status_code, body, path)
        raise AssertionError("unreachable")

    def post(self, path: str, body: dict) -> Reply:
        return self.request("POST", path, json_body=body)
