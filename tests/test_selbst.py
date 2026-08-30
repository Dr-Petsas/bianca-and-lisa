"""Offline-Tests fuer den Teststudio-Selbst-Anruf (kein Netz)."""

from tests.baukasten import selbst


def test_ton_studio_trifft_nicht_live_bianca():
    assert selbst.ton_studio("/api/audio/x.wav") == "api/selbst/ton/audio/x.wav"
    assert selbst.ton_studio("/api/audio-stream/y.wav") == "api/selbst/ton/audio-stream/y.wav"
    u = selbst.ton_studio("http://127.0.0.1:8098/api/audio/z.wav")
    assert u == "api/selbst/ton/audio/z.wav"
    assert "8096" not in u and "8098" not in u


def test_ton_studio_leer():
    assert selbst.ton_studio("") == ""
    assert selbst.ton_studio(None) == ""


def test_merke_zuege():
    a = selbst.LiveAnruf()
    a.schliessen()
    selbst.merke_anrufer(a, "Hallo")
    selbst.merke_bianca(a, {"text": "Guten Tag", "audioUrl": "api/selbst/ton/audio/a.wav"})
    assert a.zuege[0]["wer"] == "anrufer"
    assert a.zuege[1]["wer"] == "bianca"
    b = selbst.bericht_bauen(a)
    assert b["id"] == "selbst-anruf"
    assert len(b["zuege"]) == 2
