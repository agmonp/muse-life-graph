"""Settings loaded once from .env (see .env.example).

The downloadable app (`mlg/desktop.py`, built with PyInstaller) keeps everything of its user in one folder,
%LOCALAPPDATA%/MuseLifeGraph: their keys in settings.env (written by the first-run setup screen) and the
caches, fingerprints and films in data/. Their photos are read where they are and never copied there.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
FROZEN = getattr(sys, "frozen", False)                      # running from the built app
DESKTOP = FROZEN or os.environ.get("MLG_DESKTOP") == "1"    # the downloadable app (or a test of it from source)
HOME = Path(os.environ.get("MLG_HOME") or Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "MuseLifeGraph")
USER_ENV = HOME / "settings.env"
# the hosted site keeps its data on a volume (MLG_DATA); the app in the user's folder; a checkout in data/
DATA = Path(os.environ.get("MLG_DATA") or (HOME / "data" if DESKTOP else ROOT / "data"))
CACHE = DATA / "cache"


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model: str
    audio_model: str
    heavy_model: str
    transcribe_model: str
    image_model: str
    sam_model: str
    baseten_key: str
    baseten_url: str
    baseten_model: str
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    # where the looking and the writing happen (MLG_MODE):
    #   cloud - everything on Meta's API (fast, needs a key, costs a little per photo)
    #   mixed - every call that carries a picture, a video or a sound runs on this computer's own model;
    #           only text (descriptions, the film's words) goes to the API
    #   local - everything on this computer's own model: no key, no cost, nothing leaves the machine
    mode: str
    local_url: str
    local_model: str

    def configured(self) -> bool:
        """Enough to work: a graph database, and a Meta key unless everything runs on this computer."""
        return bool((self.api_key or self.mode == "local") and self.neo4j_uri and self.neo4j_password)

    def require_key(self) -> str:
        if not self.api_key:
            raise RuntimeError("MODEL_API_KEY is empty - put your Meta Model API key in .env")
        return self.api_key


@lru_cache(maxsize=1)
def settings() -> Settings:
    if DESKTOP:
        load_dotenv(USER_ENV, override=True)   # cleared and re-read after the setup screen saves
    else:
        load_dotenv(ROOT / ".env")
    e = os.environ.get
    return Settings(
        api_key=e("MODEL_API_KEY", ""),
        base_url=e("META_BASE_URL", "https://api.meta.ai/v1").rstrip("/"),
        model=e("MUSE_MODEL", "muse-spark-1.3"),
        audio_model=e("MUSE_AUDIO_MODEL", "muse-spark-1.2"),
        heavy_model=e("MUSE_HEAVY_MODEL", "muse-wonder-1.0"),
        transcribe_model=e("MUSE_TRANSCRIBE_MODEL", "muse-voice-transcribe-1.0"),
        image_model=e("MUSE_IMAGE_MODEL", "muse-image-1.0"),
        sam_model=e("SAM_MODEL", "sam-3.1"),
        baseten_key=e("BASETEN_API_KEY", ""),
        baseten_url=e("BASETEN_BASE_URL", "https://inference.baseten.co/v1").rstrip("/"),
        baseten_model=e("BASETEN_MODEL", "meta-models/muse-spark-open-1026"),
        neo4j_uri=e("NEO4J_URI", ""),
        neo4j_user=e("NEO4J_USER", "neo4j"),
        neo4j_password=e("NEO4J_PASSWORD", ""),
        mode=e("MLG_MODE", "cloud").strip().lower() if e("MLG_MODE", "cloud").strip().lower() in MODES else "cloud",
        local_url=e("MLG_LOCAL_URL", "http://localhost:11434/v1").rstrip("/"),   # Ollama; LM Studio is :1234/v1
        local_model=e("MLG_LOCAL_MODEL", ""),
    )


MODES = ("cloud", "mixed", "local")
