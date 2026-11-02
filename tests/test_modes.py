"""Where each call goes in the three modes: cloud, mixed (pictures stay here) and local (everything here)."""
from pathlib import Path

import pytest

from mlg import config
from mlg.muse import chat


@pytest.fixture
def mode(monkeypatch):
    def set_mode(m, model="muse-glimmer"):
        monkeypatch.setenv("MLG_MODE", m)
        monkeypatch.setenv("MLG_LOCAL_MODEL", model)
        monkeypatch.setenv("MODEL_API_KEY", "test-key")
        config.settings.cache_clear()
    yield set_mode
    config.settings.cache_clear()


PIC = chat.Part("image", path=Path("x.jpg"))


def test_cloud_sends_everything_to_meta(mode):
    mode("cloud")
    assert chat.provider_for(None, [chat.text("hi"), PIC]).name == "meta"


def test_mixed_keeps_pictures_here_and_sends_text(mode):
    mode("mixed")
    assert chat.provider_for(None, [chat.text("hi"), PIC]).name == "local"
    assert chat.provider_for(None, [chat.text("write the film")]).name == "meta"
    assert chat.provider_for("search", [chat.text("q")]).name in ("meta", "baseten")


def test_local_keeps_everything_here(mode):
    mode("local")
    p = chat.provider_for(None, [chat.text("write the film")])
    assert p.name == "local" and p.default_model == "muse-glimmer"
    assert p.http.base_url == "http://localhost:11434/v1"


def test_local_needs_a_model(mode):
    mode("local", model="")
    with pytest.raises(RuntimeError, match="local model"):
        chat.provider_for(None, [chat.text("x")])


def test_unknown_mode_is_cloud(mode):
    mode("banana")
    assert config.settings().mode == "cloud"


def test_local_mode_needs_no_meta_key(mode, monkeypatch):
    mode("local")
    monkeypatch.setenv("MODEL_API_KEY", "")
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_PASSWORD", "pw")
    config.settings.cache_clear()
    assert config.settings().configured()


def test_sound_never_goes_out_from_local(monkeypatch):
    from mlg.muse import local_asr
    monkeypatch.setattr(local_asr, "available", lambda: False)
    out = chat.local_parts([chat.text("listen:"), chat.Part("audio", path=Path("a.wav"))])
    assert [p.kind for p in out] == ["text", "text"] and "left out" in out[1].text


def test_heard_on_this_computer(monkeypatch):
    from mlg.muse import local_asr
    monkeypatch.setattr(local_asr, "available", lambda: True)
    monkeypatch.setattr(local_asr, "segments", lambda p: [(0.0, 1.5, "mazal tov")])
    out = chat.local_parts([chat.Part("audio", path=Path("a.wav"))])
    assert "mazal tov" in out[0].text and "this computer" in out[0].text


def test_local_call_goes_to_the_local_server(mode, monkeypatch):
    mode("local")
    seen = {}

    class Reply:
        status, seconds, headers = 200, 0.1, {}
        body = {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {}}

    def post(self, path, body, log=None):
        seen.update(url=self.base_url + path, model=body["model"], effort="reasoning_effort" in body)
        return Reply()

    monkeypatch.setattr(chat.MetaHTTP, "post", post)
    ans = chat.ask([chat.text("hi")], schema={"type": "object"}, model="muse-wonder-1.0", use_cache=False)
    assert ans.data == {"ok": True} and ans.provider == "local" and ans.served_by == "this computer's own model"
    assert seen == {"url": "http://localhost:11434/v1/chat/completions", "model": "muse-glimmer", "effort": False}
