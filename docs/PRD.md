# Muse Life Graph — PRD & Architecture (v2, 2026-10-26)

> Working name. Meta Global AI Developer Hackathon, Oct 26 – Nov 4 2026
> (submission 9:00 PM ET Nov 4 = **04:00 Nov 5 Israel time**).
> New work only: this repository was started from an empty folder on 2026-10-26.

## 1. Pitch

**"You have 40,000 photos and your mom's 70th birthday is tomorrow."**

Muse Life Graph turns a raw pile of photos, videos and voice notes into a reasoned,
evidence-backed graph of a life — and then a crew of Muse agents uses that graph to
write, cut, *watch*, critique and re-cut a personal film (birthday, wedding, friends,
family) from one sentence. Friends and family add their own photos and recorded
blessings through a link; Muse weaves their actual words into the film.

The film is the product. The graph and the listening layer ("Shema") are the engine.

### Why this is not a "simple image analyzer" or "basic RAG"
1. **Multi-pass reasoning** — per-item perception, cross-item identity resolution,
   event hierarchy, cross-item relationship inference.
2. **Agentic film crew** — Producer, Researcher, Screenwriter, Picture Checker,
   Director, Editor, Sound, Narrator, Critic; each a Muse agent with tools.
3. **Muse watches its own cut** — the Critic receives the rendered draft *video*,
   returns timestamped notes, the Editor revises; v1 vs v2 shown side by side.
4. **Every claim has evidence** — bbox / timestamp / rationale / confidence on every
   edge, shown in the UI ("Edit Room").
5. **Measured** — an eval set with before/after numbers (see §9).

## 2. Meta tools in use

| Tool | ID | Role |
|---|---|---|
| Muse Spark 1.3 | `muse-spark-1.3` | Main brain: vision, video understanding, reasoning, tool calls, structured JSON |
| Muse Spark 1.2 | `muse-spark-1.2` | Audio understanding (tone, emotion, laughter) — 1.3 audio is "not fully supported" |
| Muse Wonder | `muse-wonder-1.0` | Heavy steps only: Screenwriter, Critic watching the draft video |
| Muse Voice Transcribe | `muse-voice-transcribe-1.0` | Hebrew + English ASR, diarization, turn timestamps, realtime WebSocket |
| SAM 3.1 | `sam-3.1` | Person masks: identity crops, subject-tracking 9:16 reframing, depth/bokeh |
| Muse Image | `muse-image-1.0` | Title cards, posters, chapter cards (always labelled "generated") |
| Muse Spark Open | `meta-models/muse-spark-open-1026` (Baseten, hackathon ID) | Bulk perception on credits; targets the open-weights bonus prize |
| Meta open weights (MusicGen, MMS-TTS) | local / Modal GPU | Original music per film, narration — **pending rules check** |
| Muse Code | — | Used for part of the development; noted in README |

Base URL `https://api.meta.ai/v1`, `Authorization: Bearer $MODEL_API_KEY`
(OpenAI-compatible for chat/responses; Voice Transcribe has its own REST/WS shape).
**Never use `-contributor` model variants** — they train on our (private) content.

## 3. Hero flow (the demo)

1. Upload a folder (≈150 photos, 10 clips) → live graph grows; Muse asks smart
   questions ("Is this Dana?" with two photos) and the graph visibly improves.
2. Type: *"A 90-second film for Mom's 70th, warm and funny, ending with the grandkids."*
3. **Edit Room** shows the crew working live, every decision with its evidence
   (rejected shots shown with ✕ and the reason).
4. Draft v1 renders → Critic watches it → notes with timestamps → v2. Side by side.
5. Family blessings recorded through the share link appear as voice + subtitles.
6. Pause the film anywhere: "Who is this? When was this?" → answered from the graph.
7. Export a WhatsApp-ready MP4 (opens on a title card, never a black frame).

Demo language: English UI and narration; Hebrew family speech shown with English
subtitles (multilingual is a feature).

## 4. Architecture

```
            ┌──────────────────── Life Graph (Neo4j) ────────────────────┐
            │ Person · Moment/Event/Chapter · Place · Emotion · Inference │
            │ Conversation · Utterance · Blessing · Film/Scene/Shot       │
            └──▲───────────────────▲────────────────────────▲────────────┘
               │                   │                        │
 ┌─────────────┴───────┐ ┌─────────┴───────────┐ ┌──────────┴──────────────┐
 │ A. Perceive         │ │ B. Shema (voice)    │ │ C. Film Studio          │
 │ ingest→pHash dedup  │ │ record/upload/link  │ │ brief→crew agents       │
 │ →date (EXIF/content)│ │ →Voice Transcribe   │ │ →storyboard→EDL (JSON)  │
 │ →SAM person crops   │ │ →Spark 1.2 analysis │ │ →render (ffmpeg, SAM    │
 │ →Spark JSON+evidence│ │ →consent gate       │ │  reframe, music, voice) │
 │ →critic→resolve     │ │ →graph              │ │ →Critic watches→revise  │
 └─────────────────────┘ └─────────────────────┘ └─────────────────────────┘
                 D. Ask agent: NL → read-only Cypher tools → cited answer
```

Stack: Python 3.13, FastAPI + plain HTML/JS (no build step, phone layout),
Neo4j 5 (AuraDB Free for the live demo; local instance optional),
ffmpeg for render, Modal for GPU jobs in the hosted demo.
All Muse calls go through one adapter with retries, token/cost logging and a
response cache keyed by `sha256(model + prompt + media)`.

### Package layout
```
mlg/muse      adapters: chat (Spark/Wonder/Open), transcribe, sam, image; capability probe
mlg/ingest    hashing, perceptual dedup (pHash; keyframe fingerprint for video), dates
mlg/perceive  per-item prompt build, Pydantic schema, repair loop, critic
mlg/graph     driver, constraints, MERGE writers, read-only Cypher tools
mlg/reason    identity resolution, event clustering, relationships, chapters
mlg/shema     recorder endpoints, blessing links, transcription, voice analysis, consent
mlg/studio    crew agents, storyboard, EDL, renderer, music, narration, critic loop
mlg/agent     Ask agent
mlg/web       FastAPI app + static UI (Edit Room, graph, studio, player)
mlg/evals     labelled set + metrics scripts
```

## 5. Graph schema

Every relationship carries `confidence`, `evidence[]` (media/frame/observation ids +
bbox or [t0,t1]), `rationale`, `inferred_by`, `created_at`.

**Nodes**
- `Person {id, name?, aliases[], appearance, is_owner, confirmed}` — named only from the
  seeded roster, explicit speech/text, or user confirmation.
- `MediaItem {id=sha256, kind, path, taken_at, date_source, phash, duration_s?}`, `Frame {id, ts_s}`
- `Observation {id, bbox?, ts_s?, expression, pose}` — one person in one item (reversible merges)
- `Moment` → `Event {type, title, start, end}` → `LifeChapter {title, narrative}`
- `Location`, `Object`, `Activity`, `Emotion {name, valence, arousal}` (fixed taxonomy), `Topic`
- `Conversation {start, end, summary, mood, consent}`, `Utterance {text, lang, t0, t1, tone, emotion}`
- `Blessing {from_name, for_person, media_id, consent=films}` (via share link)
- `Inference {claim, rationale, confidence, model, pass, status}`
- `Film {brief, kind, status, version}`, `Scene {order, intent, line}`, `Shot {in, out, reframe, transition}`

**Relationships**
- `(Person)-[:OBSERVED_AS]->(Observation)-[:IN]->(MediaItem|Frame)`
- `(Person)-[:PRESENT_AT {role}]->(Moment|Event)`
- `(Person)-[:INTERACTED_WITH {kind, valence, moment_id}]->(Person)`
- `(Person)-[:RELATED_TO {kind, since?}]->(Person)` (aggregated across items)
- `(Person)-[:FELT {intensity, cue, moment_id}]->(Emotion)`; `(Moment|Event)-[:EVOKED_EMOTION]->(Emotion)`
- `(Moment)-[:PART_OF]->(Event)-[:PART_OF]->(LifeChapter)`; `(Moment|Event)-[:OCCURRED_AT]->(Location)`
- `(Moment)-[:DEPICTED_IN]->(MediaItem)`; `(Event)-[:PRECEDED {gap_days}]->(Event)`
- `(Person)-[:SPOKE_IN {share}]->(Conversation)`; `(Person)-[:SAID]->(Utterance)-[:IN]->(MediaItem)`
- `(Utterance)-[:MENTIONS|ABOUT]->(Person|Topic|Event)`; `(Conversation)-[:DURING]->(Moment|Event)`
- `(Blessing)-[:FOR]->(Person)`, `(Blessing)-[:HAS_UTTERANCE]->(Utterance)`
- `(Person)-[:SAME_AS_CANDIDATE {score, status}]->(Person)`
- `(Film)-[:FOR]->(Person|Event)`, `(Film)-[:HAS_SCENE]->(Scene)-[:HAS_SHOT]->(Shot)-[:USES]->(MediaItem|Utterance)`
- `(Scene)-[:BASED_ON]->(Moment)`, `(Film)-[:REVISED_FROM {critic_notes}]->(Film)`
- `(Inference)-[:SUPPORTS]->(…)`, `(Inference)-[:BASED_ON]->(MediaItem)`

Constraints: unique `id` per id-keyed label, unique `Emotion.name`, `Topic.name`;
indexes on `MediaItem.taken_at`, `Event.start`, `Person.name`.

## 6. Prompts (drafts; final versions live in `mlg/prompts/`)

### 6.1 Perceive (Spark 1.3, structured output)
Key rules: JSON only; every node/edge has confidence + evidence (bbox or [t0,t1] + cue);
never guess a real name (roster match with stated features, or name spoken/written);
one-sentence rationale tied to observable cues; `basis: observed|inferred` (inferred
≤0.8, relationships ≤0.7 unless stated); fixed emotion taxonomy attributed to a person
(FELT) or the scene (EVOKED); content-based dating for scans/film; ≤8 salient objects;
`open_questions` for the human. Output: `scene{summary, setting, date, event_guess}`,
`people[]`, `objects[]`, `activities[]`, `utterances[]`, `edges[]`, `open_questions[]`.
Context injected: KNOWN_PEOPLE, NEIGHBOUR_ITEMS summaries, MEDIA_META.

### 6.2 Shema conversation / blessing analysis (Spark 1.2, audio + diarized transcript)
Output: speakers (label → person_id|null), summary, mood with [t0,t1] evidence,
per-turn emotion/tone/laughter, topics, decisions, promises, mentions, and
`film_worthy` lines (short, clear, emotionally strong). Emotion only from audible cues;
never name an unmatched speaker; quote speech exactly.

### 6.3 Screenwriter (Wonder)
Input: producer intent + ≤80 moments (+ film-worthy voice lines). Output: title,
logline, arc, scenes `{order, intent, moment_ids[], narration|null, voice_line_ids[],
target_sec, emotion}`. Each scene uses only its own moments; never invent events;
thin material → shorter film, never padding; first scene opens on a clear face.

### 6.4 Picture Checker (Spark 1.3, contact sheet per scene)
Keep / drop each candidate against the scene text with a reason (wrong place, wrong
people, closed eyes, blur, emotion not visible). Drops are shown in the Edit Room.

### 6.5 Critic (Wonder, rendered draft video + EDL)
Timestamped notes: repeats, pacing, arc (peak placement), text/picture mismatch,
audio clashes, black frames. Output maps notes to EDL operations the Editor can apply.

### 6.6 Ask agent (Spark 1.3, tools)
Tools: `run_cypher` (read-only, ≤6 hops), `get_media`, `person_timeline`.
Every sentence cites node/media ids, rendered as thumbnails / audio snippets.

## 7. Shema: privacy by design
- Recording is **user-initiated** (a moment, a dinner, a blessing link) — no always-on.
- Default: audio deleted after analysis; text + insights kept. Per-clip consent:
  `private | graph | films`.
- Unenrolled voices stay "Speaker B": no name, no voiceprint.
- Blessing links are scoped to one film and one recipient; contributors see what is stored.
- Demo data: one consenting family only; no personal media ever committed to the repo.

## 8. Roadmap

| Day | Date | Build | Done when |
|---|---|---|---|
| 0 | Sun 26.10 | Repo, venv, PRD, keys | Initial commit |
| 1 | Mon 27.10 | Muse adapters (chat, transcribe, SAM, image), capability probe, **cost/latency of Wonder watching video**, ingest + pHash, schema | Probe report committed |
| 2 | Tue 28.10 | Perceive → graph, roster seeding, "Is this X?" questions | 50 items in a browsable graph |
| 3 | Wed 29.10 | **Walking skeleton**: brief → simple script → ffmpeg film | First real film out (ugly is fine) |
| 4 | Thu 30.10 | Edit Room, Picture Checker, Critic watches draft, v1 vs v2 | Visible, explained improvement |
| 5 | Fri 31.10 | Shema: blessing link, recorder, Transcribe, Spark 1.2, voice + subtitles in film | Hebrew blessing in film with English subtitles |
| 6 | Sat 01.11 | Film polish: SAM reframing, music, English narration, Muse Image cards | Birthday film you'd actually send |
| 7 | Sun 02.11 | Evals + numbers, pause-and-ask, wedding/friends/family templates | Metrics table in README |
| 8 | Mon 03.11 | Hosted demo (Modal + AuraDB), README, record 3-min video | Draft submission |
| 9 | Tue 04.11 | Buffer, submit before 04:00 Israel time (Nov 5) | Submitted |

Cut order if late: causal edges → life chapters → Muse Image cards → generated music
(use a free library) → narration (subtitles only). Never cut: perceive → brief → film →
critic loop.

## 9. Evaluation
Hand-labelled set (40 photos, 5 conversations/blessings, 3 briefs):
- Picture/text match rate before vs after the Picture Checker
- Person identification precision/recall with vs without roster
- Critic: v1 vs v2 blind preference (5+ viewers) and issue counts
- Time and $ per film; tokens per stage
Results go in the README and the demo video.

## 10. Official rules and judging (participant guide, read 2026-10-26)
- Problem statement: **Build for Your World**. Repo must be public; max team 4.
- Demo may only show what was built during the hackathon, and must make that clear
  (README section "Built during the hackathon" + commit history from 2026-10-26).
- Anti-projects include basic RAG, simple image analyzers and **personality analyzers**:
  Shema must not score people's personality, positivity or vocabulary. It extracts
  moments, quotes, topics and events for films and the graph only. No medical advice.
- Only use code, data, music and media we have rights to.
- Stage 2 rubric, equal weight 0–10: **Impact, Use of Meta AI Tooling, Technical Depth &
  Execution, Demo**. Submission = public repo + 3-minute video + live product.
- Bonus prizes we target: Best Build on Meta Open Weight Models ($10K, Muse Spark Open on
  Baseten), Best Agentic Use-Case ($5K, the film crew), Best Creative Build ($5K, Muse
  Image/Wonder), Most Viral on X ($20K, post a film), Community Vote ($10K).
- Credits: Meta $150 (claim link "coming soon", needs a card on the account, set a spend
  limit), Baseten $100 + 2M TPM (form, reviewed by use case), Modal $100 (first 1,000),
  Fireworks $25 (shortlist).
- Workshops (ET): Oct 27 Agents 101, Oct 28 Verifiable Agents, Oct 30 Fireworks; Discord
  office hours weekdays 10–11 AM ET.

## 11. Risks & open questions
- Still to ask on Discord: are non-Muse open models (MusicGen, MMS-TTS) fine as
  supporting tools? (Rules only require rights to all assets.)
- Meta API is in preview: rate limits unknown → cache everything, pre-process demo data.
- Wonder video cost/latency unknown → measured on Day 1; fallback = keyframe contact sheet + EDL to Spark.
- Local GPU is shared with the owner's other nightly jobs → GPU work on Modal.
- Hebrew TTS quality → English narration in the demo.
- MusicGen / MMS-TTS weights are CC-BY-NC → fine for the hackathon, not for production.
- Track: Indie by default; Startup if the share-link loop + hosted demo are solid.
