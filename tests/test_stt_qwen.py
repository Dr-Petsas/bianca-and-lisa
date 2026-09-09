"""W-STT-QWEN: Qwen3-ASR auf der 3060 ist Biancas primaeres Ohr.

Die Tests laufen ohne Netz und beweisen insbesondere, dass ein konfigurierter
Qwen-Pfad weder Whisper noch ElevenLabs als stillen Rueckfall verwendet.
"""

from __future__ import annotations

import time

import kern.stt as stt


class _Antwort:
    status_code = 200

    def __init__(self, text: str):
        self.text = text

    def json(self):
        return {"text": self.text}


class _FakeLokal:
    def __init__(self, text: str = "Parakeet hat uebernommen"):
        self.text = text
        self.aufrufe = []

    def post(self, url, files=None, data=None, **kwargs):
        self.aufrufe.append((url, files or {}, data or {}))
        return _Antwort(self.text)


BLOB = b"x" * 2000


def _umgebung(fn, *, qwen_ws, stt_base="http://parakeet:8212"):
    fake_lokal = _FakeLokal()
    alt = (
        stt.STT_QWEN_BASE,
        stt.STT_QWEN_KEY,
        stt.STT_WHISPER_BASE,
        stt.STT_BASE,
        stt.ELEVENLABS_API_KEY,
        stt._CLIENT,
        stt._qwen_pause_bis,
        stt._qwen_ws,
        stt._whisper_ws,
        stt._pcm16k,
        stt.httpx.post,
    )
    stt.STT_QWEN_BASE = "ws://3060-test:8222"
    stt.STT_QWEN_KEY = "qwen-test-token"
    # Absichtlich gesetzt: Qwen-Modus muss selbst dann von Whisper getrennt sein.
    stt.STT_WHISPER_BASE = "ws://whisper-darf-nicht-laufen:8092"
    stt.STT_BASE = stt_base
    stt.ELEVENLABS_API_KEY = "eleven-darf-nicht-laufen"
    stt._CLIENT = fake_lokal
    stt._qwen_pause_bis = 0.0
    stt._qwen_ws = qwen_ws
    stt._pcm16k = lambda audio, mime: b"p" * 4000

    def _whisper_alarm(*args, **kwargs):
        raise AssertionError("Qwen-Modus hat Whisper aufgerufen")

    def _scribe_alarm(*args, **kwargs):
        raise AssertionError("Qwen-Modus hat ElevenLabs aufgerufen")

    stt._whisper_ws = _whisper_alarm
    stt.httpx.post = _scribe_alarm
    try:
        fn(fake_lokal)
    finally:
        (
            stt.STT_QWEN_BASE,
            stt.STT_QWEN_KEY,
            stt.STT_WHISPER_BASE,
            stt.STT_BASE,
            stt.ELEVENLABS_API_KEY,
            stt._CLIENT,
            stt._qwen_pause_bis,
            stt._qwen_ws,
            stt._whisper_ws,
            stt._pcm16k,
            stt.httpx.post,
        ) = alt


def test_qwen_ist_primaer_und_whisper_bleibt_unberuehrt():
    def lauf(fake_lokal):
        text = stt.transcribe(BLOB, keywords="Petsas,Patrikis")
        assert text == "Ich moechte zu Doktor Petsas."
        assert not fake_lokal.aufrufe

    _umgebung(
        lauf,
        qwen_ws=lambda pcm, keywords="": "Ich moechte zu Doktor Petsas.",
    )


def test_qwen_ausfall_faellt_nur_auf_parakeet_und_pausiert():
    def kaputt(pcm, keywords=""):
        raise RuntimeError("qwen_timeout")

    def lauf(fake_lokal):
        assert stt.transcribe(BLOB) == "Parakeet hat uebernommen"
        assert fake_lokal.aufrufe
        assert stt._qwen_pause_bis > time.time()

    _umgebung(lauf, qwen_ws=kaputt)


def test_qwen_pause_geht_direkt_zu_parakeet():
    def nie(pcm, keywords=""):
        raise AssertionError("Qwen darf in der Pause nicht aufgerufen werden")

    def lauf(fake_lokal):
        stt._qwen_pause_bis = time.time() + 10
        assert stt.transcribe(BLOB) == "Parakeet hat uebernommen"
        assert fake_lokal.aufrufe

    _umgebung(lauf, qwen_ws=nie)


def test_qwen_ausfall_ohne_parakeet_wirft_statt_whisper_oder_scribe():
    def kaputt(pcm, keywords=""):
        raise RuntimeError("qwen_timeout")

    def lauf(_fake_lokal):
        try:
            stt.transcribe(BLOB)
        except RuntimeError as exc:
            assert "stt_qwen" in str(exc)
        else:
            raise AssertionError("Qwen-Ausfall ohne Parakeet muss sichtbar sein")

    _umgebung(lauf, qwen_ws=kaputt, stt_base="")


def test_qwen_url_und_health_anzeige():
    alt = (
        stt.STT_QWEN_BASE,
        stt.STT_WHISPER_BASE,
        stt.STT_BASE,
        stt._qwen_pause_bis,
    )
    try:
        stt.STT_QWEN_BASE = "https://paraqwenstt.pickadoc-tunnel.com/"
        stt.STT_WHISPER_BASE = "ws://whisper:8092"
        stt.STT_BASE = "http://parakeet:8212"
        stt._qwen_pause_bis = 0.0
        assert stt._qwen_ws_url() == (
            "wss://paraqwenstt.pickadoc-tunnel.com/stream"
        )
        assert stt.bereit()
        assert stt.engine_anzeige() == (
            "Qwen3-ASR 1.7B (3060) + Parakeet-Rueckfall"
        )
        stt._qwen_pause_bis = time.time() + 10
        assert stt.engine_anzeige() == "Parakeet (lokal, Qwen pausiert)"
    finally:
        (
            stt.STT_QWEN_BASE,
            stt.STT_WHISPER_BASE,
            stt.STT_BASE,
            stt._qwen_pause_bis,
        ) = alt
