"""Settings loaded once from .env (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("MLG_DATA") or ROOT / "data")   # the hosted site keeps its data on a volume
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

    def require_key(self) -> str:
        if not self.api_key:
            raise RuntimeError("MODEL_API_KEY is empty - put your Meta Model API key in .env")
        return self.api_key


@lru_cache(maxsize=1)
def settings() -> Settings:
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
    )
