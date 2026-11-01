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
⟨paste after posting, see the draft at the bottom⟩

**Public GitHub Repository**
https://github.com/agmonp/muse-life-graph

**3-Minute Demo Video (YouTube)**
⟨YouTube link, unlisted or public⟩

---

## Project Description

**One sentence in, a family film out — written, cut, watched and re-cut by a crew of Meta Muse agents that
checks its own work.**

**Try it (2 minutes):** https://agmonporat--muse-life-graph-web.us-east.modal.run · access code: ⟨code⟩
1. Home plays a film the crew made. 2. Search "when did we go to the beach with the kids?" — the answer cites
the photos it used. 3. Films → open "Taya Growing Up" → see the critic's timestamped notes, the first cut vs
the re-cut, and the blind test. 4. Make your own film (about 7 minutes). Names are read-only.
Or run it on your own photos: Windows download in the README.

Every family has twenty thousand photos nobody looks at, and old faces nobody can name anymore. Muse Life
Graph turns that pile into a reasoned life graph, and then a crew of Meta Muse agents turns one sentence
("a film of Taya growing up, warm and simple") into a personal film that the crew writes, cuts, *watches*
and re-cuts.

It is not a photo tagger or a chat over photos. Muse Spark perceives every photo, video (keyframes plus
soundtrack) and voice note into a strict schema with evidence, including when a scan was taken and why it
thinks so. Copies are found by perceptual fingerprint. A name goes on a face only when two independent keys
agree (a local face fingerprint and a second witness); unnamed faces are grouped so one answer names many.
Everything lands in a Neo4j graph, where network science (a significant-tie backbone, Louvain circles,
bridges) shows the circles of a life forming and fading year by year.

The film crew is a chain of agents with tools: Researcher (queries the graph), Producer (Muse Spark),
Screenwriter (Muse Wonder), a pause where the crew asks the owner what only they know (answers go back into
the graph), a Picture Checker that looks at every picture against its narration, an Editor, Sound (Meta
MusicGen score and SeamlessM4T narration on a local GPU), and a Critic: Muse Wonder watches the rendered
draft video, puts timestamped notes on the timeline, the Editor re-cuts, and a blind test shows Wonder both
cuts without saying which is the revision. Search and questions in any language are answered only from the
moments found, with citations. Search, memory titles, circle names and the Picture Checker run on
**Muse Spark Open (open weights) on Baseten**.

Measured on real data (docs/EVALS.md): in a blind test over all 8 finished films, shown in both orders, Muse preferred the critic's re-cut in 12 of 16 viewings; face fingerprints alone name people at 80% precision against the owner's earlier records, and the app's two-key links at 93%; a film takes a median 7 minutes and $3 of model calls. Measuring also exposed a bug (the Picture Checker's rejections were ignored), now fixed.

Built from an empty repository during the hackathon (first commit 2026-10-26). The demo library is the
author's own family photos, shared with consent; names and reference faces were imported as data from the
author's earlier private database. It is designed to run on your own computer, so your family's photos never have to
leave home: anyone can download it for Windows (link in the README) and use it with their own Meta key and a free
graph database.

Fits the bonus categories: **open weights** (Muse Spark Open on Baseten runs search, titles, circles and the
Picture Checker; MusicGen and SeamlessM4T on a home GPU), **agentic** (a crew that pauses to ask, critiques
and re-cuts), **creative** (a personal film from one sentence).

## Describe your use of Meta products to build the submitted project

- **Muse Spark 1.3 (Meta Model API):** the perception pass, one call per photo, video or voice note with
  images, video keyframes and the audio track together, returning a strict JSON schema (who, what, where,
  when with a reason, what was said, evidence). Also the Producer agent and the narration-vs-picture judge in
  our evals.
- **Muse Spark Open (`meta-models/muse-spark-open-1026`) on Baseten:** reads every search question into
  people, years and search words (Hebrew and English), writes cited answers, titled all 473 memories, names the
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
