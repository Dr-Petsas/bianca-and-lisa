"""Diagnosespur beweist die Audio-Pipeline und ihren STT-Gewinner."""

from __future__ import annotations

from kern import stt, stt_spur


def test_spur_markiert_parakeet_als_audio_gewinner(monkeypatch):
    monkeypatch.setattr(stt, "STT_BASE", "http://parakeet:8212")
    monkeypatch.setattr(stt, "STT_QWEN_BASE", "")
    monkeypatch.setattr(stt, "STT_QWEN_FINAL_BASE", "")

    def fake_transcribe(audio, **_kwargs):
        stt_spur._lokal.parakeet_text = "Guten Morgen."
        return "Guten Morgen."

    monkeypatch.setattr(stt, "transcribe", fake_transcribe)
    text, info = stt_spur.transcribe(
        b"x" * 2400, mime="audio/wav", name="anrufer.wav",
    )
    assert text == "Guten Morgen."
    assert info["pipeline"] == "audio"
    assert info["bytes"] == 2400
    assert info["winner"] == "parakeet"
    assert info["parakeet"]["text"] == text


def test_spur_zeigt_qwen_uebernahme_und_beide_texte(monkeypatch):
    monkeypatch.setattr(stt, "STT_BASE", "http://parakeet:8212")
    monkeypatch.setattr(stt, "STT_QWEN_BASE", "ws://qwen:8222")
    monkeypatch.setattr(stt, "STT_QWEN_FINAL_BASE", "")

    kandidat = {
        "text": "Ein Röntgenbild.",
        "source": "qwen",
        "authoritative": True,
        "reason": "",
    }

    def fake_transcribe(_audio, **_kwargs):
        stt_spur._lokal.parakeet_text = "Ein Rhön Biepfeld."
        stt_spur._lokal.qwen_entschieden = True
        stt_spur._lokal.qwen_uebernommen = True
        stt_spur._lokal.qwen_kandidat = kandidat
        return kandidat["text"]

    monkeypatch.setattr(stt, "transcribe", fake_transcribe)
    text, info = stt_spur.transcribe(b"x" * 2400)
    assert text == "Ein Röntgenbild."
    assert info["winner"] == "qwen"
    assert info["parakeet"]["text"] == "Ein Rhön Biepfeld."
    assert info["qwen"]["text"] == "Ein Röntgenbild."
    assert info["qwen"]["status"] == "uebernommen"


def test_spur_entfernt_englischen_rohtext_und_markiert_filter(monkeypatch):
    monkeypatch.setattr(stt, "STT_BASE", "http://parakeet:8212")
    monkeypatch.setattr(stt, "STT_QWEN_BASE", "")
    monkeypatch.setattr(stt, "STT_QWEN_FINAL_BASE", "")

    def fake_transcribe(_audio, **_kwargs):
        text = stt._sauber("Damn it.")
        stt_spur._lokal.parakeet_text = text
        return text

    monkeypatch.setattr(stt, "transcribe", fake_transcribe)
    text, info = stt_spur.transcribe(b"x" * 2400)

    assert text == ""
    assert info["parakeet"]["text"] == ""
    assert info["filter"] == {
        "reason": "englisch-oder-stille",
        "discarded": True,
    }


def test_spur_reicht_antworttyp_durch_und_markiert_filterkontext(monkeypatch):
    monkeypatch.setattr(stt, "STT_BASE", "http://parakeet:8212")
    monkeypatch.setattr(stt, "STT_QWEN_BASE", "")
    monkeypatch.setattr(stt, "STT_QWEN_FINAL_BASE", "")
    gesehen = {}

    def fake_transcribe(_audio, **kwargs):
        gesehen.update(kwargs)
        stt._SPRACHWACHE.grund = "englisch-oder-stille"
        stt_spur._lokal.parakeet_text = ""
        return ""

    monkeypatch.setattr(stt, "transcribe", fake_transcribe)
    text, info = stt_spur.transcribe(
        b"x" * 2400,
        sprachkontext="ja_nein",
    )

    assert text == ""
    assert gesehen["sprachkontext"] == "ja_nein"
    assert info["filter"] == {
        "reason": "englisch-oder-stille",
        "discarded": True,
        "context": "ja_nein",
    }
