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
