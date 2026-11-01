# Submission form draft (Agmon submits; do not submit from here)

Form: Cerebral Valley → Meta AI Developer Hackathon → Submit. Deadline **Wed Nov 4, 9:00 PM ET = Thu Nov 5,
04:00 Israel**. The form has no live-demo field: the link and the judges' access code go in **Project
Description** (and the README says the code is there).

---

**Team Name**
Muse Life Graph

**Team Members**
Agmon Porat (solo)

**Track**
Indie Developer

**Problem statement**
Build for Your World

**X post link (Most Viral)**
https://x.com/agmondp/status/2116815391280468008

**Public GitHub Repository**
https://github.com/agmonp/muse-life-graph

**3-Minute Demo Video (YouTube)**
https://youtu.be/JX4o7B06awk

---

## Project Description

Muse Life Graph: one sentence in, a family film out. A crew of Meta Muse agents writes it, cuts it, watches its own draft and re-cuts it.

TRY IT (2 minutes)
Live demo: https://agmonporat--muse-life-graph-web.us-east.modal.run  ·  access code: ⟨data/site_code.txt⟩
1. Home plays a film the crew made.
2. Search "when did we go to the beach with the kids?" and see the answer cite the photos it used.
3. Films > "Taya Growing Up": the critic's timestamped notes, first cut vs re-cut, and the blind test.
4. Make your own film (about 7 minutes). Names are read-only.
Run it on your own photos: Windows download in the README.

THE PROBLEM
Families keep thousands of photos and videos nobody looks at, and old faces nobody can name anymore. Turning them into a birthday or wedding film takes days of searching and editing. Today's AI tools either tag pictures or generate once without checking the result.

WHAT IT DOES
- Understands, not just tags: Muse Spark perceives each photo, video (keyframes and soundtrack together) and voice note into a strict schema with evidence, including when an undated scan was taken and why it thinks so. Copies are found by perceptual fingerprint.
- Names people carefully: a name goes on a face only when two independent keys agree (a local face fingerprint and a second witness). Unnamed faces are grouped, so one answer names many.
- Builds a life graph: Neo4j holds moments, people, places and evidence; network science (backbone, Louvain circles, bridges) shows the circles of a life forming and fading year by year.
- Makes the film with an agent crew: Researcher (queries the graph) > Producer (Muse Spark) > Screenwriter (Muse Wonder) > pauses to ask the owner what only they know > Picture Checker (Muse Spark Open) > Editor > Sound (MusicGen score, SeamlessM4T narration) > Critic: Muse Wonder watches the rendered draft video and gives timestamped notes > re-cut > blind test.
- Search and ask in any language, answered only from the moments found, with citations.

RESULTS (real data, docs/EVALS.md)
- Blind test over all 8 finished films, in both orders: Muse Wonder preferred the critic's re-cut in 12 of 16 viewings.
- Two-key face links: 93% precision (face fingerprints alone: 80%).
- A film takes a median 7 minutes and $3 of model calls.
- Measuring exposed a real bug (the Picture Checker's rejections were ignored), now fixed.

WHAT'S NEW
Everything shown was built from an empty repository during the hackathon (first commit Oct 26; git log shows every step). The demo library is the author's own family photos, shared with consent. The only thing brought in from before is data: names and reference faces from the author's earlier private database.

PRIVATE BY DESIGN
Built to run on your own computer, so family photos never have to leave home: download for Windows, bring your own Meta key and a free graph database.

BONUS CATEGORIES
Open weights (Muse Spark Open on Baseten for search, titles, circles and the Picture Checker; MusicGen and SeamlessM4T on a home GPU) · Agentic (a crew that pauses to ask, critiques and re-cuts) · Creative (a personal film from one sentence).

## Describe your use of Meta products to build the submitted project

- **Muse Spark 1.3 (Meta Model API):** the perception pass, one call per photo, video or voice note with
  images, video keyframes and the audio track together, returning a strict JSON schema (who, what, where,
  when with a reason, what was said, evidence). Also the Producer agent and the narration-vs-picture judge in
  our evals.
- **Muse Spark Open (`meta-models/muse-spark-open-1026`) on Baseten:** reads every search question into
  people, years and search words (Hebrew and English), writes cited answers, titles all 473 memories, names the
  circles of people, and runs the Picture Checker on film scenes with images. A provider switch in
  `mlg/muse/chat.py` routes these tasks to it, falls back to the API on failure, and logs which model served
  each call; the app shows "served by Muse Spark Open on Baseten". We measured it against the Muse Spark API on
  the same 30 inputs (agreement, latency, cost).
- **Muse Wonder 1.0:** the Screenwriter, and the Critic that watches the rendered draft *video* and returns
  timestamped edit notes; also the blind judge between the first cut and the re-cut.
- **Muse Spark 1.2:** listens to blessings recorded through a share link and picks the film-worthy lines.
- **Muse Voice Transcribe 1.0:** Hebrew and English speech with speaker turns and timestamps.
- **Meta open weights on our own GPU:** MusicGen medium (an original score per film) and SeamlessM4T v2 (the
  narrator; 5.1% word error rate vs 16.5% for MMS-TTS in our test). A Modal A10G is the fallback.
- **Facebook "Download your information":** the importer reads the export in place.
- SAM 3.1 and Muse Image were integrated and probed on day 1 (Muse Image built our first fictional test
  family) but are not in the live pipeline.

## Why are Meta's models important to your solution?

The product needs one model family that can look at a photo, a video and its soundtrack *together* and
answer in a strict schema, because a family moment is all three: the picture, who is speaking, and what they
said, often in Hebrew. Muse Spark does that in one call; Muse Wonder can watch a rendered film and give
timed notes, which is what lets the crew critique and re-cut its own work instead of just generating once.
Meta's open weights matter as much: Muse Spark Open lets the reasoning parts (search, titling, naming circles,
checking pictures) run on open weights, and MusicGen and SeamlessM4T run on a home GPU. The direction is a
life graph that runs on your own computer, because nobody should have to upload twenty years of family photos
to understand them.

## Provide feedback from your experience using partner technologies

- **Baseten (Muse Spark Open):** the OpenAI-compatible endpoint worked on the first call with strict JSON
  schema output and image input. Two things to know: the model reasons first (about 300–700 reasoning tokens
  per call), so a small `max_tokens` returns an empty answer with no error — a clear "ran out of tokens"
  signal would save time; and image calls were much slower and more variable than on the Muse Spark API in
  our test (median 15.4 s vs 6.1 s for Picture Checker scenes, one call over 5 minutes), while text calls were close. Usage reporting
  (reasoning tokens, cached tokens) was complete and easy to log.
- **Modal:** the whole hosted demo is one Modal app: a FastAPI container with a volume for media copies and
  films, and an A10G function for MusicGen and SeamlessM4T that only spins up when the owner's PC is off.
  Deploys take seconds and the volume CLI made moving data easy. Wishes: requiring a payment method before any
  GPU use, even with credits, slowed us down on day 5, and a per-app spend cap in the CLI would be welcome.
  Git Bash on Windows rewrites `/`-paths in `modal volume` commands; PowerShell works.
- **Fireworks:** we claimed credits but did not use them in the final build; Baseten covered the open-weights
  path.

---

## Survey questions

Answer these yourself.

---

## Draft X post (Most Viral)

> I gave an AI film crew 20,000 family photos and one sentence: "a film of my daughter growing up."
>
> It found her in photos I'd forgotten, asked me who the faces were, watched its own first cut, took notes,
> and re-cut it. Then it picked the better version blind.
>
> Built in 10 days on @Meta Muse + Muse Spark Open. Runs on your own computer. 🎬
>
> ⟨video clip: 20–30 s of the Taya film + the crew log⟩
> github.com/agmonp/muse-life-graph #MetaAIHackathon

Shorter alternative:

> 20,000 photos. 1 sentence. A crew of Meta Muse agents wrote, cut, watched and re-cut a film of my daughter
> growing up, then blind-tested its own edit. Built in 10 days. ⟨clip⟩ #MetaAIHackathon

Post tips: attach the video natively (not a YouTube link); tag Meta AI and Cerebral Valley (check their current handles); post in the
US morning (16:00–18:00 Israel) and reply to the first comments within the hour.
