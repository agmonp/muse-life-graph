# Capability probe

Run 2026-10-26 13:19 against `https://api.meta.ai/v1`.

| Probe | OK | Model s | Wall s | Tokens in/out | $ | Note |
|---|---|---|---|---|---|---|
| spark-1.3 text | yes | 1.47 | 0.0 | 13/34 | 0.00016 | pong |
| spark-1.3 image | yes | 3.99 | 0.01 | 2101/715 | 0.00566 | The photo shows a multi-generational family — an older woman with gray curly hair at the center, flanked by a smiling man with glasses and a woman with a ponytail, along with a young boy and a young g |
| spark-1.3 image + json_schema (chat) | yes | 4.28 | 0.01 | 2086/805 | 0.00603 | {"emotions": [{"confidence": 0.98, "name": "joy"}, {"confidence": 0.96, "name": "happiness"}, {"confidence": 0.92, "name": "excitement"}, {"confidence": 0.9, "name": "affection"}], "people_count": 5,  |
| spark-1.3 image + json_schema (responses) | yes | 3.97 | 0.01 | 2086/708 | 0.00562 | {"emotions": [{"confidence": 0.98, "name": "joy"}, {"confidence": 0.96, "name": "happiness"}, {"confidence": 0.9, "name": "affection"}], "people_count": 5, "summary": "A family of five celebrates outd |
| spark-1.2 audio | yes | 3.8 | 0.0 | 174/486 | 0.00228 | Transcription:  "Happy birthday mom. 70 years old and still the fastest dancer in the family. Do you remember the trip to the beach in 1994? We laughed all day."  Speaker's Tone and Emotion:  The spea |
| spark-1.3 audio | yes | 8.6 | 0.0 | 174/1158 | 0.00514 | **Transcription:** Happy birthday Mom. 70 years old and still the fastest dancer in the family. Do you remember the trip to the beach in 1994? We laughed all day. We  **Speaker's Tone and Emotion:** W |
| spark-1.3 video (10 s) | yes | 16.33 | 0.0 | 2772/2297 | 0.01323 | no speech heard; 1) What moves on screen:  The background does **not** move. It is 6 static vertical bars left to right: red, bright green, yellow, dark blue, magenta, cyan.  Wh |
| wonder-1.0 video (10 s) | yes | 17.42 | 0.01 | 2052/2173 | 0.05167 | HEARS SPEECH; **1) What moves on screen**  The background itself does not move. It is six static vertical colour bars, left to right: red, green, yellow, blue, magenta, and c |
| spark-1.2 keyframes + audio (chat) | yes | 6.55 | 0.0 | 1698/1250 | 0.00744 | HEARS SPEECH; Across the 5 keyframes the underlying image is a static SMPTE color bar test pattern - vertical bars in red, green, yellow, blue, magenta, cyan with a grey-blue |
| spark-1.3 keyframes + audio (chat) | yes | 12.77 | 0.0 | 1698/1476 | 0.0084 | HEARS SPEECH; The 5 frames show the same static background with animated foreground graphics.  Background is unchanged: 6 vertical color bars left to right - red, green, yell |
| voice-transcribe diarization | yes |  | 0.01 |  |  | 1 turns: Happy birthday, mom. 70 years old and still the fastest dancer in the family. Do you remember the trip to the beach in 1994? We laughed all day. |
| sam-3.1 image | yes |  | 4.33 |  |  | 5 people; first box (1326, 495, 1833, 1127); mask px 195696 |
| sam-3.1 video | yes |  | 0.0 |  |  | 0 objects over 0 frames |
