# Screen recording cut list — revised November 1, 2026

Recorded-owner export: `data/video/demo_with_agmon.mp4`, using `beats_owner.json` and the actual clock in
`OWNER_EDIT.md`. The table below is the earlier camera-placeholder version.

Authoritative edit: `beats.json`. Render: `python docs/video/assemble.py --out data/video/draft_v2.mp4`.

1920×1080, 30 fps. Large white 64 px bold captions, actual font-width wrapping, up to two lines on an 88% black lower band. Camera review cards use 64 px white bold text instead of the previous small grey text. Camera takes and all screen captures run at natural speed. The 25-second family film is the final shot. No app code or hosted UI was changed for this edit.

| Final time | Source | Source in | Duration | Framing |
|---|---|---|---|---|
| 0:00 | make.mp4 | 4 s | 6 s | Full frame |
| 0:06 | Camera A | 0 s | 12 s | Full frame |
| 0:18 | library.mp4 | 4 s | 6 s | Full frame |
| 0:24 | add.mp4 | 3 s | 6 s | Full frame |
| 0:30 | dated.mp4 | 1.5 s | 8 s | 1480:832:440:0 |
| 0:38 | faces.mp4 | 9 s | 8 s | Full frame |
| 0:46 | connections.mp4 | 8 s | 8 s | Full frame |
| 0:54 | search.mp4 | 16 s | 6 s | Full frame |
| 1:00 | Camera B | 0 s | 12 s | Full frame |
| 1:12 | make.mp4 | 1 s | 8 s | Full frame |
| 1:20 | make.mp4 | 60 s | 8 s | 1440:810:400:0 |
| 1:28 | crew.mp4 | 3 s | 8 s | Full frame |
| 1:36 | crew.mp4 | 14 s | 8 s | 1440:810:400:100 |
| 1:44 | film.mp4 | 2 s | 10 s | 1440:810:400:100 |
| 1:54 | film.mp4 | 15 s | 9 s | 1440:810:400:100 |
| 2:03 | home.mp4 | 4 s | 9 s | Full frame |
| 2:12 | stack_card.png | 0 s | 6 s | Full frame |
| 2:18 | search.mp4 | 19 s | 5 s | Full frame |
| 2:23 | Camera C | 0 s | 12 s | Full frame |
| 2:35 | taya_v2.mp4 | 48 s | 25 s | Full frame |

## Recording and audio status

The three camera cards reserve 12 seconds each. Four planned voiceovers go over 0:30–0:38, 0:46–0:54, 1:28–1:36 and 2:03–2:12. Their text is in `RECORDING.md`. These are planned slots, not aligned subtitles of recorded speech. They must be checked against the owner's real takes before submission. The final family clip keeps its existing music and speech; the app captures have no incidental sound. No synthetic voice was substituted for the owner.

## Evidence and limits

The labels emphasize graph reasoning, uncertain identity questions, the visible agent log, Spark Open picture checks, the video critic, revision and the measured blind comparison. The 12/16 result is from `docs/EVALS.md`, on eight films shown in both orders. The earlier graph contributed names and reference faces as data only. The tools card says built during the hackathon, without claiming ten completed days before that date.

Reference check: first-party `assemble.py` and `capture.py` inspected in the checkout. XERJ `ownlife` search for `assemble screen camera caption` returned unrelated importer code and a stale index warning; that did not establish coverage. The existing FFmpeg drawtext/drawbox approach is retained; only editorial timing, text wrapping and layout were adapted. No third-party implementation was copied.

Review fixes: the old timeline recording displayed an error, so the opening scope shot was re-recorded on the actual Memories screen (`library.mp4`). The question beat starts at source second 60, when the questions are visible.
