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

## Run it on your own photos

Muse Life Graph is made to run where your photos are: on your own computer. It reads a folder or your
Facebook / Instagram download in place; the files never leave your machine. Only the calls to Meta's models
(Muse Spark, Wonder, Voice Transcribe, Muse Image) and the graph database (Neo4j AuraDB Free, or a local Neo4j)
are online. The [live demo](https://agmonporat--muse-life-graph-web.us-east.modal.run) shows one family's graph,
shared with consent; there names are read-only.

```powershell
git clone https://github.com/agmonp/muse-life-graph; cd muse-life-graph
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env        # your Meta Model API key + Neo4j connection
.\.venv\Scripts\python.exe -m mlg.graph.db                                  # create the graph schema
.\.venv\Scripts\python.exe -m uvicorn mlg.web.app:app --port 8800          # open http://localhost:8800
```

Then choose **Add photos**: a folder on your computer, or the .zip files from Meta's *Download your information*.
The app fingerprints every file (copies are set aside), shows the cost before Muse looks (about $0.006 a photo),
and builds your memories, people, circles and films. Music and narration use Meta's open MusicGen and SeamlessM4T
on your GPU (`.venv-gpu`, see `mlg/studio/gpu_worker.py`); without one, films get on-screen captions.

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

## Phase 2 (built 2026-10-26): perceive -> graph

The fictional "Cohen family" demo set used during phases 2-7 was removed on 2026-10-27; the app now works on the
owner's own photos only (added from a folder or a Facebook / Instagram export).

| Module | What it does |
|---|---|
| `mlg/people.py` | Known people with reference crops (`python -m mlg.people add/list`) |
| `mlg/perceive/run.py` | One Muse call per item: rules prompt + known people's reference photos + same-day moments + the media. Photos as images, videos as keyframes + audio track, audio as audio + diarized transcript |
| `mlg/perceive/critic.py` | Code-enforced rules: drop claims without evidence, cap inferred confidence, cap voice-only identities and turn them into questions |
| `mlg/graph/write.py` | Idempotent per-item sub-graph: MediaItem, Moment, Observations, Objects, Activities, Utterances, typed edges with evidence |

```powershell
.\.venv\Scripts\python.exe -m mlg.ingest.scan <your photo folder>
.\.venv\Scripts\python.exe -m mlg.perceive.run --workers 6
```

## Phases 3-7 (built 2026-10-26/27): the film studio

| Module | What it does |
|---|---|
| `mlg/studio/research.py` | The Researcher: every usable moment from the graph, with who is in it, what was said, and faces it could not name |
| `mlg/studio/templates.py` | Story shapes for birthday, wedding/anniversary, friends and family films: beats, time shares, rules |
| `mlg/studio/plan.py` | Producer (Muse Spark) -> Screenwriter (Muse Wonder) -> code check of every claim; hollow replies are retried |
| `mlg/studio/ask.py` | Pause and ask: before cutting, the crew asks the owner what only they know ("Is this young woman in the 1995 scan Ruth?", "Which picture for the peak?"); answers go into the graph |
| `mlg/studio/checker.py` | Picture Checker: Muse looks at every picture of every scene before the cut |
| `mlg/studio/edit.py`, `render.py` | Editor (deterministic edit list) and renderer |
| `mlg/studio/sound.py`, `gpu_worker.py` | Narrator (Meta SeamlessM4T v2) and score (Meta MusicGen medium) on the local GPU |
| `mlg/studio/critic.py` | Critic: Muse Wonder watches the draft and gives notes the editor applies; it scores v1 and v2 |
| `mlg/shema/blessings.py` | Blessings through a link: Voice Transcribe + Muse Spark pick the film-worthy lines |
| `mlg/library.py` | Memories (moments that belong together, titled by Muse Spark), timeline, people, who-appears-with-whom |
| `mlg/search.py` | Search and ask in any language: Muse Spark reads the question, a full-text index over what Muse saw ranks the moments, Spark answers with citations |
| `mlg/imports.py` | Add photos: a folder on this computer or a Facebook / Instagram export (.zip); copies set aside, cost shown before Muse looks |
| `mlg/web/` | The app at `/`: home, memories, timeline, people, connections, search, films (the Edit Room), "Who is this?", add photos; blessing page `/bless/<token>` |
| `scripts/evals.py` | Measurements -> [docs/EVALS.md](docs/EVALS.md) |

```powershell
.\.venv\Scripts\python.exe -m uvicorn mlg.web.app:app --port 8800       # then open http://localhost:8800
.\.venv\Scripts\python.exe -m mlg.studio.make "A 60-second film for grandma Ruth's 70th" --template birthday
.\.venv\Scripts\python.exe scripts\evals.py --films 6
```

## License

Apache-2.0
