# Recorded-owner export review — November 1, 2026

Deliverable: `data/video/demo_with_agmon.mp4`. The media stays local and git-ignored.
Rebuild with `transcribe_local.py`, `owner_edit.py`, then `assemble.py --beats docs/video/beats_owner.json`.
`OWNER_EDIT.md` records the source and destination clocks; `owner_subtitles.srt` is the owner-speech sidecar.
The family film retains its own burned-in English subtitles.

## Edit

- Opens on real app use. The final family film runs only at 2:35–3:00.
- All recording cards are replaced. 65.23 seconds of the owner's real voice, with 21.5 seconds on camera;
  other chosen speech plays over the relevant app screens. No synthetic voice, speed-up or lip-sync edit.
- The supplied video is 478×850 portrait. The presenter is contained intact in the landscape frame,
  with black side margins, preserving the full original background and face.
- Large 64 px bold white captions; measured wrapping, balanced short second lines, no competing subtitle
  and explanatory-caption layers. Named-model ASR spellings were corrected; the raw ASR remains local.
- The spoken claim that everything runs locally was omitted; the earlier wish to analyze locally remains
  in the opening. The explanatory caption states that the earlier graph contributed data only.
- Existing local MusicGen scores provide a quiet instrumental bed through 2:35; the family film then keeps
  its original sound. Voice master uses a 70 Hz high-pass and one whole-recording loudness normalization.

## Verification and limits

- The complete export decodes without FFmpeg errors; 1920×1080 H.264 at 30 fps, 5,400 video frames,
  stereo AAC at 48 kHz. The video, audio and container durations are checked against 180 seconds.
- Every selected source range fits its source, speech fits its scene at natural speed, subtitle cues
  are ordered and bounded, all captions fit two measured lines, and no camera placeholder remains.
- Visual review covered the whole timeline via decoded frames and focused views of the presenter,
  Picture Checker, spoken model names and transition into the final family film.
- A second offline Whisper transcription of the rendered product section recovered all selected spoken
  sections, including the first/last phrases and blind-test result. This supports intelligibility and
  intact edits; ASR is not a human listening review and can miss pronunciation problems.
- Audio measured about -17 LUFS integrated and -1 dBTP on the mixed export before removal of the final
  AAC padding; no overload was measured. **listening_review: not_performed**. Full audible quality still
  needs the owner's playback review.

## Local transcription and optional editor

The automatic permission review rejected an upload of the supplied voice recording to the Meta speech
API because external sharing of that recording had not been explicitly approved. The recording was then
transcribed entirely offline with the existing cached Whisper small model. No model was downloaded and
no successful audio upload occurred. `faster-whisper` and its small runtime dependencies were installed
in the existing venv for this offline edit, separately from the product requirements.

The supplied [mrpaidsocial editor](https://github.com/mrpaidsocial/mrpaidsocial-video-editor-agent) was
reviewed, but not installed: the existing Python/FFmpeg edit already supplied the required source cuts,
word-timed subtitles, original-camera placement and audio mixing. No third-party editor code was copied.

Reference API check: SYSTRAN/faster-whisper, MIT, pinned local reference commit
`9e472ae9de8bb374552f531f752654554b76b2d6`, `README.md:183–205` (segment and word timestamps).
The mechanism uses its public API and keeps source time separate from final-video time.
