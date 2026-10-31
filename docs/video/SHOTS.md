# Shot list (Screen track)

All screens recorded at 1920×1080, 30 fps, by `docs/video/capture.py` (Playwright driving Chrome, headless)
against a local copy of the demo site: `scripts/run_site_local.py --port 8803 --data data/capture/data --gpu
local` (the same code and data as the live site). Raw files land in `data/video/` (git-ignored: they show the
family). `docs/video/beats.json` is the cut list `docs/video/assemble.py` renders into `data/video/draft.mp4`.

| # | File | What the capture does (and when) | Used at | In → length |
|---|---|---|---|---|
| 1 | `taya_v2.mp4` | The hero film, "Taya Growing Up", after the critic (75 s, English subtitles, MusicGen score) | 0:00 hook | 45 s → 12 s |
| 2 | `timeline.mp4` | `#/timeline`, page settles 2.5 s, then a slow scroll down the years for 9 s | 0:27 problem | 3 s → 4 s |
| 3 | `faces.mp4` | `#/faces` ("Name a face once, name it everywhere", open-face counter), scroll at 4–7 s, hover and click **Yes, ‹name›** at about 13 s, toast "saved for this visit" | 0:31 problem; 0:51 identity | 2 s → 4 s; 11 s → 7 s |
| 4 | `add.mp4` | `#/add`: "On your own computer", four steps (install, key, folder or Meta download, your life graph) | 0:35 dedup caption | 3 s → 8 s |
| 5 | `dated.mp4` | Timeline, then the viewer on a 1970s scan: the picture, "How Muse dated it" (flared jeans, old cars, faded print vs a 2009 upload) | 0:43 | 2.5 s → 8 s |
| 6 | `connections.mp4` | `#/connections`, ▶ pressed at about 5 s: circles appear and fade year by year for 22 s | 0:58 | 9 s → 7 s |
| 7 | `make.mp4` | `#/films`: the sentence typed, **Make the film**, "Planning…" and the crew log starting; at about 52 s the crew stops with *A few things only you know* (two faces) and both are answered. The page stays on the questions after that, so the rest of the 20-minute recording is not used | 1:15, 1:25 | 1 s → 10 s; 52 s → 13 s |
| 7b | `crew.mp4` | The film `make` recorded, finished (`film_20261031_175659`): scenes with the Picture Checker's ✕ and *checked by Muse Spark Open on Baseten*, then the crew log scrolling (*Picture Checker 2 changes · served by Muse Spark Open on Baseten*, "eyes closed on key face"); zoomed with a crop | 1:38 | 14 s → 10 s |
| 8 | `film.mp4` | The finished hero film page: both cuts, critic note 1 clicked (the first cut jumps to 1:02), scenes with the checker's verdicts, the crew log | 1:48 | 3 s → 14 s |
| 9 | `home.mp4` | Home: the hero film playing, critic's notes on the time strip, the **Blind test: Muse preferred the re-cut** card | 2:02 | 4 s → 8 s |
| 10 | `search.mp4` | Home → types "When did we go to the beach with the kids?" → cited answer, "Answered by Muse Spark Open on Baseten", the matching photos | 2:10 | 13 s → 5 s |
| 11 | `taya_v2.mp4` | The hero film again: the birthday wish with its English subtitle through the ending | 2:15 payoff | 46 s → 25 s |
| 12 | `stack_card.png` | `docs/video/stack_card.py`: Built on Meta, the five model rows, built in 10 days, the repo | 2:45 | 7 s |

The on-camera parts (0:12, 1:05, 2:40, 2:52) are black gaps in the draft with the line printed in grey, so the
draft can be watched end to end before you record.

To re-capture one screen: `.venv\Scripts\python.exe docs\video\capture.py --only faces` (`--make --only make`
records a new film, about 5–10 minutes and a few dollars of Muse calls).
