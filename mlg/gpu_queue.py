"""GPU work for the hosted site, done by the owner's own computer.

The site has no GPU. When a film needs a score (MusicGen) or narration (SeamlessM4T), its jobs
wait here; `scripts/gpu_bridge.py` on the owner's PC asks for work every few seconds over
HTTPS, runs the jobs on the local GPU and posts the audio back. The PC only makes outgoing
requests, so nothing at home is opened to the internet. When no bridge has asked for work
lately, `alive()` is false and the film is made with on-screen captions instead.
"""
from __future__ import annotations

import base64
import collections
import threading
import time
import uuid

ALIVE_S = 30          # a bridge that polled within this long is there
CLAIM_S = 60          # a job nobody picks up in this long fails over to captions
_LOCK = threading.Lock()
_PENDING: collections.deque = collections.deque()
_BATCHES: dict[str, dict] = {}
_LAST_POLL = 0.0


def alive() -> bool:
    return time.time() - _LAST_POLL < ALIVE_S


def run(jobs: list[dict], timeout: float = 1200) -> list[dict]:
    """Queue jobs for the bridge and wait; each result carries the audio as bytes in `wav`."""
    bid = uuid.uuid4().hex
    batch = {"jobs": jobs, "done": threading.Event(), "claimed": threading.Event(), "results": None}
    with _LOCK:
        _BATCHES[bid] = batch
        _PENDING.append(bid)
    try:
        if not batch["claimed"].wait(CLAIM_S):
            raise RuntimeError("the GPU computer did not pick up the job")
        if not batch["done"].wait(timeout):
            raise RuntimeError("the GPU computer took too long")
        return batch["results"]
    finally:
        with _LOCK:
            _BATCHES.pop(bid, None)
            if bid in _PENDING:
                _PENDING.remove(bid)


def next_batch() -> dict | None:
    """Called by the bridge: counts as a heartbeat, hands over the oldest waiting batch."""
    global _LAST_POLL
    with _LOCK:
        _LAST_POLL = time.time()
        while _PENDING:
            bid = _PENDING.popleft()
            if bid in _BATCHES:
                _BATCHES[bid]["claimed"].set()
                return {"id": bid, "jobs": _BATCHES[bid]["jobs"]}
    return None


def finish(bid: str, results: list[dict]) -> bool:
    with _LOCK:
        batch = _BATCHES.get(bid)
    if not batch:
        return False
    for r in results:
        if r.get("wav_b64"):
            r["wav"] = base64.b64decode(r.pop("wav_b64"))
    batch["results"] = results
    batch["done"].set()
    return True
