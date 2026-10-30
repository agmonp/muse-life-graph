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


def _sb():
    ms = {
        "m1": {"id": "m1", "kind": "photo", "date": "1994-07-01", "faces": [], "people": [],
               "unknown": [{"obs": "s1:p1", "bbox": [200, 170, 730, 970], "candidate": "person:ruth",
                            "appearance": "young woman, curly hair"}]},
        "m2": {"id": "m2", "kind": "photo", "date": "2025-10-12", "faces": [], "people": [], "unknown": []},
        "m3": {"id": "m3", "kind": "photo", "date": "2025-10-12", "faces": [], "people": [], "unknown": []},
        "m4": {"id": "m4", "kind": "photo", "date": "2024-02-03", "faces": [], "people": [],
               "unknown": [{"obs": "s4:p9", "bbox": [0, 0, 50, 50], "candidate": None}]},   # background face
    }
    script = {"scenes": [{"order": 1, "intent": "young Ruth", "moment_ids": ["m1", "m4"]},
                         {"order": 2, "intent": "the peak", "moment_ids": ["m2"]},
                         {"order": 3, "intent": "together", "moment_ids": ["m3"]}],
              "doubts": [{"scene_order": 2, "question": "Which picture for the peak?", "why": "",
                          "options": [{"moment_id": "m2", "label": "candles"}, {"moment_id": "m3", "label": "hug"}],
                          "chosen_moment_id": "m2"}]}
    return {"moments": ms, "script": script, "brief": {"subject_ids": ["person:ruth"]}}


ROSTER = [{"id": "person:ruth", "name": "Ruth"}, {"id": "person:david", "name": "David"}]


def test_questions_ask_about_clear_unnamed_faces_and_doubts():
    from mlg.studio import ask
    qs = ask.questions(_sb(), ROSTER)
    assert [q["kind"] for q in qs] == ["identity", "pick"]          # the tiny background face is not asked
    assert qs[0]["text"].startswith("Is this Ruth?") and qs[0]["options"][0]["value"] == "person:ruth"
    assert qs[1]["default"] == "m2"


def test_owner_pick_swaps_pictures_between_scenes():
    from mlg.studio import ask
    sb = _sb()
    qs = ask.questions(sb, ROSTER)
    ask.apply(sb, qs, {"q1": "other", "q2": "m3"})
    sc = sb["script"]["scenes"]
    assert sc[1]["moment_ids"] == ["m3"] and sc[2]["moment_ids"] == ["m2"]   # swapped, nothing used twice
    assert sc[0]["moment_ids"] == ["m4"]                                       # "not Ruth": picture out


def test_no_answer_keeps_the_crews_picks():
    from mlg.studio import ask
    sb = _sb()
    qs = ask.questions(sb, ROSTER)
    ask.apply(sb, qs, {})
    assert sb["script"]["scenes"][1]["moment_ids"] == ["m2"] and all("crew" in q["outcome"] for q in qs)


def test_template_check_reports_missing_and_misordered_beats():
    from mlg.studio import templates
    assert templates.pick("anniversary") == "wedding" and templates.pick("birthday", "friends") == "friends"
    script = {"scenes": [{"order": 1, "beat": "hello"}, {"order": 2, "beat": "peak"},
                         {"order": 3, "beat": "roots"}, {"order": 4, "beat": "together"}]}
    notes = templates.check("birthday", script)
    assert "no scene for the 'people' beat" in notes and "beats out of the template's order" in notes
    assert "people (~20 s)" in templates.for_prompt("birthday", 70)


def test_hollow_script_is_detected_and_repaired():
    from mlg.studio import plan
    known = {"a": {"kind": "photo", "duration": None}, "v": {"kind": "video", "duration": 22.0}}
    s = {"logline": "", "arc": [], "closing_card": "",
         "scenes": [{"beat": "hello", "intent": "", "moment_ids": ["a"], "target_sec": 0},
                    {"beat": "peak", "intent": "", "moment_ids": ["a", "v"], "target_sec": 0}]}
    assert plan.hollow(s)
    plan.repair(s, known, {"template": "birthday", "title": "Happy 70th"})
    assert [x["target_sec"] for x in s["scenes"]] == [4.0, 19.0] and s["scenes"][1]["intent"] == "peak"
    assert s["arc"] == ["hello", "peak"] and s["closing_card"] == "Happy 70th" and not plan.hollow(s)


def _blessing_world():
    def photo(i, year, summary, who="person:ruth"):
        return {"id": f"p{i}", "kind": "photo", "date": f"{year}-05-01", "summary": summary, "event": None,
                "objects": [], "people": ["Ruth"], "faces": [{"id": who, "bbox": [0, 0, 500, 500]}], "said": [],
                "duration": None, "path": f"p{i}.jpg"}
    ms = [photo(1, 1975, "Ruth at her wedding"), photo(2, 1995, "Ruth baking bread in the kitchen"),
          photo(3, 2010, "Ruth in the garden with roses"), photo(4, 2020, "Ruth laughing at the table"),
          photo(5, 2021, "Noam on a bike", who="person:noam"),
          {"id": "b1", "kind": "audio", "date": "2026-10-26", "summary": "blessing", "event": "Blessing for Ruth",
           "objects": [], "people": [], "faces": [], "duration": 30.0, "path": "b1.wav",
           "said": [{"id": "u1", "text": "Grandma, your bread and your kitchen are home to me", "t0": 0.0, "t1": 6.0},
                    {"id": "u2", "text": "and your garden roses every spring, happy birthday", "t0": 6.0,
                     "t1": 17.0}]}]
    script = {"scenes": [
        {"order": 1, "moment_ids": ["p1"], "voice_line_ids": [], "target_sec": 5},
        {"order": 2, "moment_ids": ["b1"], "voice_line_ids": ["u1", "u2"], "target_sec": 18}]}
    return script, ms


def test_blessing_without_picture_gets_its_own_photos_of_the_honoree():
    from mlg.studio import plan
    script, ms = _blessing_world()
    notes = plan.picture_blessings(script, ms, ["person:ruth"], choose=lambda gaps, free: {})  # model gave nothing
    ids = script["scenes"][1]["moment_ids"]
    assert ids[-1] == "b1" and len(ids) == 3               # 17 s of words -> 2 photos, then the recording
    assert set(ids[:2]) == {"p2", "p3"}                    # the bread/kitchen and garden/roses photos
    assert "p1" not in ids and "p5" not in ids             # never a used photo, never someone else's
    assert ids[:2] == ["p2", "p3"]                         # in date order
    assert notes and "2 photo" in notes[0]


def test_blessing_pictures_follow_the_model_pick_and_skip_bad_ids():
    from mlg.studio import plan
    script, ms = _blessing_world()
    plan.picture_blessings(script, ms, ["person:ruth"], choose=lambda gaps, free: {2: ["p4", "p3"]})
    assert script["scenes"][1]["moment_ids"] == ["p4", "p3", "b1"]
    script, ms = _blessing_world()
    script["scenes"][1]["moment_ids"] = ["p4", "b1"]       # already has a picture: left alone
    assert plan.picture_blessings(script, ms, ["person:ruth"], choose=lambda g, f: 1 / 0) == []


def test_blessing_picture_that_looks_like_another_shot_is_replaced():
    from mlg.studio import plan
    script, ms = _blessing_world()
    script["scenes"][1]["moment_ids"] = ["p4", "b1"]       # p4 is the same image as scene 1's p1 (a re-send)
    twins = {frozenset({"p1", "p4"})}
    notes = plan.picture_blessings(script, ms, ["person:ruth"], choose=lambda g, f: {},
                                   looks_same=lambda a, b: frozenset({a["id"], b["id"]}) in twins)
    ids = script["scenes"][1]["moment_ids"]
    assert "p4" not in ids and ids[-1] == "b1" and set(ids[:-1]) <= {"p2", "p3"}
    assert "looks the same" in notes[0]


def test_blessing_with_no_spare_photo_joins_a_scene_with_changing_pictures():
    from mlg.studio import plan
    script, ms = _blessing_world()
    script["scenes"] = [
        {"order": 1, "moment_ids": ["p1"], "voice_line_ids": [], "target_sec": 5, "narration": None},
        {"order": 2, "moment_ids": ["p2", "p3"], "voice_line_ids": [], "target_sec": 9, "narration": "x"},
        {"order": 3, "moment_ids": ["b1"], "voice_line_ids": ["u1", "u2"], "target_sec": 18},
        {"order": 4, "moment_ids": ["p4"], "voice_line_ids": [], "target_sec": 5, "narration": None}]
    notes = plan.picture_blessings(script, ms, ["person:noam-is-not-here"], choose=lambda g, f: {})
    assert [s["order"] for s in script["scenes"]] == [1, 2, 4]
    two = script["scenes"][1]
    assert two["moment_ids"] == ["p2", "p3", "b1"] and two["voice_line_ids"] == ["u1", "u2"]
    assert two["target_sec"] == 18 and two["narration"] is None
    assert "moved over scene 2" in notes[-1]


def test_on_the_hosted_demo_an_answer_shapes_the_film_but_not_the_graph(monkeypatch):
    from mlg import identity, site
    from mlg.studio import ask
    monkeypatch.setattr(site, "MEDIA", "/site/media")
    monkeypatch.setattr(identity, "confirm_face", lambda *a, **k: (_ for _ in ()).throw(AssertionError("graph write")))
    sb = _sb()
    qs = ask.questions(sb, ROSTER)
    q = next(q for q in qs if q["kind"] == "identity")
    ask.apply(sb, qs, {q["id"]: "person:ruth"})
    m = sb["moments"][q["moment"]]
    assert any(f["id"] == "person:ruth" for f in m["faces"])          # the film knows who it is
    assert "for this film" in q["outcome"]


def test_a_film_keeps_one_of_near_identical_pictures():
    from mlg.studio import plan
    script, ms = _blessing_world()
    script["scenes"] = [{"order": 1, "moment_ids": ["p1", "p2"], "voice_line_ids": [], "target_sec": 8},
                        {"order": 2, "moment_ids": ["p3"], "voice_line_ids": [], "target_sec": 4},
                        {"order": 3, "moment_ids": ["p4", "p2"], "voice_line_ids": [], "target_sec": 8}]
    for m in ms:
        m["_looks"] = {"p2": [0b1111], "p4": [0b1110]}.get(m["id"], [int(m["id"][1:]) << 40] if m["kind"] == "photo" else [])
    notes = plan.drop_near_duplicates(script, ms)
    assert script["scenes"][2]["moment_ids"] == ["p4"] or script["scenes"][2]["moment_ids"] == ["p2"]
    assert script["scenes"][1]["moment_ids"] == ["p3"]          # a scene never loses its only picture
    assert notes
