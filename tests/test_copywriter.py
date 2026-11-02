from mlg.studio import copywriter as cw


def scene(narration="Grandma Ruth at the beach.", sec=6, voices=()):
    return {"order": 1, "narration": narration, "target_sec": sec, "moment_ids": ["m1"], "voice_line_ids": list(voices),
            "intent": "the summer at the sea"}


MOMENTS = {"m1": {"date": "1998-07-02", "kind": "photo", "event": "beach day", "place": "Tel Aviv",
                  "summary": "Ruth laughs in the waves", "faces": [{"name": "Ruth"}], "said": []}}


def vocab(sc):
    return cw._vocabulary(sc, MOMENTS, {"title": "Ruth at 70"}, ["Ruth", "David"])


def test_max_words_follows_scene_length():
    assert cw.max_words({"target_sec": 2}) == 5
    assert cw.max_words({"target_sec": 30}) == cw.MAX_WORDS
    assert cw.max_words({}) >= 4


def test_names_from_evidence_pass():
    assert cw.unsupported("That summer in Tel Aviv, Ruth owned the waves.", vocab(scene())) == []
    assert cw.unsupported("Back in 1998 - the sea knew her name.", vocab(scene())) == []


def test_invented_names_and_years_are_caught():
    assert cw.unsupported("That summer in Eilat, Ruth owned the waves.", vocab(scene())) == ["Eilat"]
    assert cw.unsupported("Ruth, in 1985, already laughing.", vocab(scene())) == ["1985"]


def test_sentence_openers_are_not_names():
    assert cw.unsupported("Sand everywhere. Laughter too.", vocab(scene())) == []


def test_off_switch(monkeypatch):
    monkeypatch.setenv("MLG_COPYWRITER", "0")
    assert cw.rewrite({"brief": {}, "script": {"scenes": []}, "moments": {}}) is None


def test_rewrite_applies_and_guards(monkeypatch):
    sb = {"brief": {"title": "Ruth at 70", "language": "en"},
          "script": {"closing_card": "Happy birthday", "scenes": [
              {**scene("Ruth at the beach."), "order": 1},
              {**scene("Ruth at the beach again.", sec=2), "order": 2},
              {**scene("Ruth smiles.", sec=6), "order": 3},
              {**scene(None, voices=["v1"]), "order": 4}]},
          "moments": MOMENTS}

    class Ans:
        served_by = "Muse Wonder"
        data = {"style": "nostalgic", "why": "a birthday look back",
                "lines": [{"order": 1, "narration": "Tel Aviv, 1998 - and Ruth already owned the sea."},
                          {"order": 2, "narration": "One more wave, one more laugh, one more summer day."},
                          {"order": 3, "narration": "Then Haifa called her name."},
                          {"order": 4, "narration": "Listen."}],
                "closing_card": "Seventy summers, Ruth."}

    monkeypatch.setenv("MLG_COPYWRITER", "1")
    monkeypatch.setattr(cw.chat, "ask", lambda *a, **k: Ans())
    out = cw.rewrite(sb, ["Ruth"])
    lines = {s["order"]: s["narration"] for s in sb["script"]["scenes"]}
    assert lines[1] == "Tel Aviv, 1998 - and Ruth already owned the sea."     # facts from the evidence
    assert lines[2] == "Ruth at the beach again."                              # too long for 2 s
    assert lines[3] == "Ruth smiles."                                          # Haifa isn't in the evidence
    assert lines[4] is None                                                    # never over a spoken voice
    assert sb["script"]["closing_card"] == "Seventy summers, Ruth."
    assert out["style"] == "nostalgic" and len(out["changes"]) == 1 and len(out["kept"]) == 2
