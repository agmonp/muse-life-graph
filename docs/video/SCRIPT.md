# Demo video script (3:00)

Two tracks. **You** = Agmon on camera, first person (about 65 s in total). **Screen** = the product demo,
captured from the app (about 115 s). Every beat names the judging criterion it serves:
**[Impact]** 30% · **[Meta]** use of Meta AI tooling 25% · **[Tech]** technical depth 20% · **[Demo]** 25%.

The draft MP4 from `docs/video/assemble.py` holds the Screen track with black gaps where You speak; record
your parts to the gap lengths below (a few seconds either way is fine, the script re-times from `beats.json`).

Rule to keep: everything on screen was built from 2026-10-26 on. The family's names, reference faces and
groups came from Agmon's older Life Graph as **data only**; say "my own family photos, imported", never show
the old app.

---

## 0:00 – 0:12 · Hook  **[Demo] [Impact]**

| | |
|---|---|
| Screen (0:00–0:12) | The Taya film, full screen, mid-film: Taya as a baby → toddler → the 2023 birthday clip with the English subtitle "Taya, I wish you a happy birthday…". Film's own music. Lower-third at 0:08: *Made by an AI film crew from one sentence.* |
| You (over the film, voice only, 0:04–0:12) | "My daughter Taya. Nobody edited this film. I typed one sentence." |

## 0:12 – 0:35 · The problem  **[Impact]**

| | |
|---|---|
| You (on camera, 0:12–0:27) | "Like every parent, I have twenty thousand photos on my phone and my Facebook — and I never look at them. Half the faces in the old ones, I can't even name anymore. The memories are there. Nobody can find them, and nobody has time to make anything from them." |
| Screen (0:27–0:35) | Fast scroll through the Timeline, then "Who is this?": *Name a face once, name it everywhere* with the open-faces counter. Caption: *One family: 3,648 photos · 69 videos · 1975–2026*. |

## 0:35 – 1:05 · Understanding, not tagging  **[Tech] [Meta]**

| | |
|---|---|
| Screen (0:35–0:43) | Add photos ("On your own computer": install, key, choose a folder or your Meta download, your life graph). Caption: *23,742 files fingerprinted · 3,393 copies set aside, 3,029 of them re-encodes no byte check would catch.* (The demo site cannot import; on your own computer the same page runs the import and shows the cost first.) |
| Screen (0:43–0:51) | A scanned childhood photo, uploaded in 2009 → the moment panel: **How Muse dated it**: *"Faded color print, flared jeans, old car models and sidewalk style point to mid-1970s, much older than 2009 upload."* Caption: *Muse Spark reads the photo, the video's frames and its sound in one call.* |
| Screen (0:51–0:58) | Who is this? → a group of faces with the suggested name → **Yes, <name>** → toast: saved for the whole group. Caption: *Two keys before a name goes in a film: a face fingerprint (YuNet + SFace) and a second witness.* |
| Screen (0:58–1:05) | Connections → press ▶: circles form and fade year by year (India Trip 2015-16, Wedding Crew 2017, the family). Caption: *Neo4j graph · Louvain circles · disparity-filter backbone · circles named by Muse Spark Open.* |
| You (voice over 0:35–0:45, then silent) | "So it doesn't tag photos. It understands them: what happened, when — even for a scan with no date — and who, with two independent keys before it will put a name in a film." |

## 1:05 – 2:15 · The crew  **[Meta] [Tech] [Demo]**

| | |
|---|---|
| You (on camera, 1:05–1:15) | "Then I ask for a film, in one sentence. And a crew of Muse agents makes it — and then watches it, and fixes it." |
| Screen (1:15–1:25) | Films → type *"A film of Taya growing up, from baby to her birthday, warm and simple."* → Make. The crew log starts streaming: Researcher → Producer (Muse Spark) → Screenwriter (Muse Wonder). |
| Screen (1:25–1:38) | **Pause and ask**: the crew stops with *A few things only you know* (a face it could not name, with the picture) → tap an answer → *Let the crew decide* for the rest → the log continues. Caption: *It asks what only you know. The answer goes into the graph for every future film.* |
| Screen (1:38–1:48) | Picture Checker: scene cards with ✕ on a dropped photo (*"eyes closed on the key face"*), a narration line rewritten; *checked by Muse Spark Open on Baseten*. |
| Screen (1:48–2:02) | First cut plays (v1) → **Critic notes on the time strip**: numbered markers, hover one: *"the 2023 clip runs 15 s, trim it"*. Editor: *applied 6 of 8 notes* → v2. Caption: *Muse Wonder watches its own draft video and gives timestamped notes.* |
| Screen (2:02–2:10) | **Blind test** card on Home: *Muse preferred the re-cut. Shown both cuts without being told which was which.* Caption: *Measured over all 8 films, both orders: the re-cut won 12 of 16 blind viewings.* |
| You (voice over 1:38–1:50) | "Every picture is checked against what the narration says. The critic watches the actual video, marks what's wrong on the timeline, and the editor re-cuts. Then a blind test: it's shown both cuts without being told which is new." |
| Screen (2:10–2:15) | Search: *When did we go to the beach with the kids?* → a cited answer, *Answered by Muse Spark Open on Baseten*. Caption: *Ask in any language. Answered only from your pictures, on Meta open weights.* |

## 2:15 – 2:45 · Payoff  **[Demo] [Impact]**

| | |
|---|---|
| Screen (2:15–2:40) | 25 s of the Taya film v2, full screen, own music and the English-subtitled birthday wish. No captions. |
| You (on camera, 2:40–2:45) | "That's the moment I'd never have found in twenty thousand photos." |

## 2:45 – 3:00 · Close  **[Meta] [Impact]**

| | |
|---|---|
| Screen (2:45–2:55) | Stack card: Muse Spark 1.3 + 1.2 · Muse Wonder · Voice Transcribe · **Muse Spark Open on Baseten (open weights)** · MusicGen · SeamlessM4T · Neo4j. Then: *Built in 10 days, from an empty repo · runs on your own computer · github.com/agmonp/muse-life-graph* |
| You (on camera, 2:45–3:00) | "It's all Meta's models, including Muse Spark Open running on open weights. I built it in ten days. And it runs on your own computer — your family's photos never have to leave home." |

---

### On-camera lines only (for the teleprompter, ~65 s)

1. (voice, over the film) "My daughter Taya. Nobody edited this film. I typed one sentence."
2. "Like every parent, I have twenty thousand photos on my phone and my Facebook — and I never look at them. Half the faces in the old ones, I can't even name anymore. The memories are there. Nobody can find them, and nobody has time to make anything from them."
3. (voice) "So it doesn't tag photos. It understands them: what happened, when — even for a scan with no date — and who, with two independent keys before it will put a name in a film."
4. "Then I ask for a film, in one sentence. And a crew of Muse agents makes it — and then watches it, and fixes it."
5. (voice) "Every picture is checked against what the narration says. The critic watches the actual video, marks what's wrong on the timeline, and the editor re-cuts. Then a blind test: it's shown both cuts without being told which is new."
6. "That's the moment I'd never have found in twenty thousand photos."
7. "It's all Meta's models, including Muse Spark Open running on open weights. I built it in ten days. And it runs on your own computer — your family's photos never have to leave home."

Recording tips: eye level, window light from the side, lapel mic if you have one; record each line 2–3 times;
keep 1 s of silence before and after each take so the cuts are clean.
