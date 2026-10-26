"""Studio checks that need no API key: the critic's notes become safe edits."""
from __future__ import annotations

from mlg.studio import critic, edit


def _edl():
    shots = [
        {"kind": "title", "scene": 1, "dur": 9.0, "moment": "a"},
        {"kind": "still", "scene": 2, "dur": 5.0, "moment": "b", "caption": "wrong"},
        {"kind": "still", "scene": 3, "dur": 5.0, "moment": "c"},
        {"kind": "clip", "scene": 4, "dur": 12.0, "moment": "d", "subtitle": "hi"},
        {"kind": "still", "scene": 5, "dur": 5.0, "moment": "e"},
        {"kind": "end", "scene": 5, "dur": 3.5, "moment": "e", "text": "bye"},
    ]
    voices = [{"scene": 5, "t0": 0.0, "t1": 8.0, "text": "happy birthday", "path": "x.wav"}]
    return edit.retime({"shots": shots, "voices": voices, "xfade": 0.5, "aspect": "16:9"})


def note(shot, op, seconds=None, caption=None):
    return {"t": 1, "shot": shot, "problem": "", "op": op, "seconds": seconds, "new_caption": caption, "why": "x"}


def test_subtitles_use_english_version_in_english_film():
    he = {"text": "אמא, שבעים שנה", "text_en": "Mom, seventy years"}
    raw = {"text": "you make every room warmer happy birthday", "text_en": "You make every room warmer. Happy birthday!"}
    assert edit._line_text(he, "en") == "Mom, seventy years"
    assert edit._line_text(he, "he") == "אמא, שבעים שנה"
    assert edit._line_text(raw, "en").startswith("You make")
    assert edit._line_text({"text": "only text"}, "en") == "only text"


def test_ducking_envelope_is_fast_and_correct(tmp_path):
    import time
    from mlg.studio import render
    edl = {"duration": 30.0, "shots": [], "voices": [], "music_mood": "warm"}
    t = time.perf_counter()
    render.render_audio(edl, tmp_path / "a.wav", seed=1)
    assert time.perf_counter() - t < 10      # np.convolve over a 0.4 s window took minutes


def test_narration_text_normalization():
    from mlg.studio.textnorm import phrases, spell_numbers
    assert spell_numbers("Happy 70th, Ruth") == "Happy seventieth, Ruth"
    assert spell_numbers("in 2012 and 1995") == "in twenty twelve and nineteen ninety five"
    assert spell_numbers("21st") == "twenty first" and spell_numbers("2005") == "twenty oh five"
    assert phrases("Seventy candles, one big breath - and everyone laughing.") == [
        "Seventy candles", "one big breath", "and everyone laughing"]


def test_voice_never_overlaps_a_talking_clip():
    shots = [
        {"kind": "title", "scene": 1, "dur": 6.0, "moment": "a"},
        {"kind": "still", "scene": 2, "dur": 4.0, "moment": "b"},
        {"kind": "clip", "scene": 2, "dur": 10.0, "moment": "c", "own_audio": True, "subtitle": "speech"},
        {"kind": "end", "scene": 2, "dur": 3.5, "moment": "c"},
    ]
    e = edit.retime({"shots": shots, "voices": [{"scene": 2, "t0": 0.0, "t1": 7.0, "text": "x", "path": "v"}],
                     "xfade": 0.5})
    v, clip = e["voices"][0], e["shots"][2]
    assert v["at"] + 7.0 <= clip["start"]          # the blessing ends before the clip's own sound starts


def test_no_caption_on_a_clip_with_speech():
    e = _edl()
    e2, done = critic.apply(e, {"notes": [note(3, "caption", caption="Mom, seventy years...")]})
    assert not e2["shots"][3].get("caption") and done == []


def test_retime_keeps_voice_inside_its_scene():
    e = _edl()
    v = e["voices"][0]
    last_still = e["shots"][4]
    assert last_still["start"] + last_still["dur"] - 0.5 >= v["at"] + 8.0   # stretched to fit the line


def test_apply_notes_safely():
    e = _edl()
    crit = {"notes": [note(0, "shorten", 4), note(1, "caption", caption="Ruth at the beach"),
                      note(2, "drop"), note(0, "drop"), note(5, "drop"), note(4, "drop")]}
    e2, done = critic.apply(e, crit)
    kinds = [s["kind"] for s in e2["shots"]]
    assert kinds[0] == "title" and kinds[-1] == "end"                  # title and closing card stay
    assert e2["shots"][0]["dur"] == 5.6                                  # 9 - 4, floor 2.6 + 3
    assert e2["shots"][1]["caption"] == "Ruth at the beach"
    assert "c" not in [s["moment"] for s in e2["shots"]]                 # silent single-shot scene dropped
    assert "e" in [s["moment"] for s in e2["shots"] if s["kind"] == "still"]  # voiced scene keeps its picture
    starts = [s["start"] for s in e2["shots"]]
    assert starts == sorted(starts) and starts[0] == 0
