# What the probe taught us (2026-10-26)

Raw numbers: [probe_report.md](probe_report.md) (regenerate with `scripts/probe.py`).

| Finding | Evidence | Design consequence |
|---|---|---|
| Strict JSON schema works on both Chat Completions (`response_format`) and Responses (`text.format`) | both probes returned valid JSON | Perceive uses Chat Completions + strict schema |
| **Native video input does not hear the audio track** | Spark 1.3 and Wonder both said "I hear no audio" on a moving clip with speech; adding an `input_audio` part to the same Responses request was ignored (+31 input tokens) | Videos are perceived as **keyframes + audio in one Chat call** |
| Keyframes + audio in one Chat call works on Spark 1.2 and 1.3 | both quoted the speech exactly and described frame-to-frame changes; 1,698 input tokens for 5 frames + 10 s audio | Default video path; native `input_video` kept only for motion-heavy questions |
| Native video is cheap in tokens (~2.7k for 10 s) but sparse | Spark 1.3 $0.013, Wonder $0.052 per 10 s clip | The Critic watching a 90 s draft on Wonder costs roughly $0.30-0.50 per pass (estimate, to measure on a real draft) |
| Audio understanding works on 1.3 too, but 1.2 is ~2x faster | 3.8 s vs 8.6 s for the same clip | Audio calls stay on `muse-spark-1.2` |
| Photo perception costs ~$0.006 and ~4 s | 2.1k in / 0.7k out tokens | 5,000 photos is about $30 and 5.5 h sequential; run 8-16 in parallel |
| Voice Transcribe is fast and exact on English | 3.4 s for 10 s of speech, one turn | **Hebrew still untested** - needs a real Hebrew sample |
| SAM 3.1 on images: ~4-12 s, correct person count | 5 people found on the party photo, masks decode with `meta-sam-parser` | Use for identity crops |
| **SAM 3.1 on video is slow at full frame rate** | 317 s for a 10 s clip at 25 fps (250 frames) | Downsample to 5 fps (or keyframes only) before SAM; never run it in the request path |
| Muse Image produced a believable family party photo | used as the probe's sample photo | Title cards / posters are viable |
