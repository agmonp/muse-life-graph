# Muse Life Graph

From a pile of photos, videos and voice notes to a reasoned life graph, and from one
sentence to a personal film that Muse writes, cuts, watches and re-cuts.

Built for the Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026) on Meta Muse
(Spark, Wonder, Voice Transcribe, SAM 3.1, Muse Image). New work, started 2026-10-26.

See [docs/PRD.md](docs/PRD.md) for the product and architecture plan.

## Setup

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env   # then fill in keys
```

## Phase 1 (built 2026-10-26)

| Module | What it does |
|---|---|
| `mlg/muse/chat.py` | Muse Spark / Wonder / Spark Open calls with text, image, audio and video parts, strict JSON-schema output, disk cache |
| `mlg/muse/transcribe.py` | Muse Voice Transcribe with speaker turns; long files cut into 9-minute windows |
| `mlg/muse/sam.py` | SAM 3.1 boxes + masks for images and video, parsed with Meta's `meta-sam-parser` |
| `mlg/muse/image.py` | Muse Image generation and reference-image edits |
| `mlg/muse/http.py` | Auth, retry policy from the API docs, usage log in `data/cache/usage.jsonl` |
| `mlg/ingest/` | sha256, perceptual duplicate detection (photo pHash, 3-frame video hash), date resolution |
| `mlg/perceive/schema.py` | The Perceive output contract (Pydantic) and its strict JSON schema |
| `mlg/graph/db.py` | Neo4j constraints and indexes |
| `scripts/probe.py` | Calls every capability once and writes `docs/probe_report.md` |

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests          # offline checks
.\.venv\Scripts\python.exe scripts\probe.py            # needs MODEL_API_KEY
.\.venv\Scripts\python.exe -m mlg.ingest.scan <folder> # hash, date, dedup
.\.venv\Scripts\python.exe -m mlg.graph.db             # needs NEO4J_* in .env
```

## License

Apache-2.0
