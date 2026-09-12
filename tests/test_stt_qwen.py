"""W-STT-QWEN-PARALLEL: 5090-Parakeet bleibt schnell, Qwen prueft parallel.

Alle Tests laufen ohne Netz. Sie beweisen insbesondere: plausible Texte
warten nicht, auffaellige Texte haben einen kleinen harten Zusatzdeckel,
Qwen staut keine Zuege und Whisper/ElevenLabs bleiben aus diesem Pfad draussen.
"""

from __future__ import annotations

import threading
import time

import kern.stt as stt


class _Antwort:
    status_code = 200

    def __init__(self, text: str):
        self.text = text

    def json(self):
        return {"text": self.text}


class _FakeLokal:
    def __init__(self, text: str = "Ich möchte zu Doktor Petsas."):
        self.text = text
        self.aufrufe = []

    def post(self, url, files=None, data=None, **kwargs):
        self.aufrufe.append((url, files or {}, data or {}, kwargs))
        return _Antwort(self.text)


BLOB = b"x" * 2000


def _kandidat(text: str, *, source: str = "qwen", authoritative: bool = True):
    return {
        "text": text,
        "source": source,
        "authoritative": authoritative,
        "reason": "",
    }


def _umgebung(
    fn,
    *,
    qwen_candidate,
    lokal_text="Ich möchte zu Doktor Petsas.",
    stt_base="http://parakeet:8212",
    grace=0.03,
):
    fake_lokal = _FakeLokal(lokal_text)
    alt = (
        stt.STT_QWEN_BASE,
        stt.STT_QWEN_FINAL_BASE,
        stt.STT_QWEN_KEY,
        stt.STT_QWEN_GRACE_S,
        stt.STT_WHISPER_BASE,
        stt.STT_BASE,
        stt.ELEVENLABS_API_KEY,
        stt._CLIENT,
        stt._qwen_pause_bis,
        stt._qwen_future,
        stt._qwen_candidate,
        stt._whisper_ws,
        stt._pcm16k,
    )
    stt.STT_QWEN_BASE = "ws://3060-test:8222"
    stt.STT_QWEN_FINAL_BASE = ""
    stt.STT_QWEN_KEY = "qwen-test-token"
    stt.STT_QWEN_GRACE_S = grace
    stt.STT_WHISPER_BASE = "ws://whisper-darf-nicht-laufen:8092"
    stt.STT_BASE = stt_base
    stt.ELEVENLABS_API_KEY = "eleven-darf-nicht-laufen"
    stt._CLIENT = fake_lokal
    stt._qwen_pause_bis = 0.0
    stt._qwen_future = None
    stt._qwen_candidate = qwen_candidate
    stt._pcm16k = lambda audio, mime: b"p" * 4000

    def _whisper_alarm(*args, **kwargs):
        raise AssertionError("Qwen-Modus hat Whisper aufgerufen")

    stt._whisper_ws = _whisper_alarm
    try:
        fn(fake_lokal)
        if stt._qwen_future is not None:
            stt._qwen_future.result(timeout=1)
    finally:
        (
            stt.STT_QWEN_BASE,
            stt.STT_QWEN_FINAL_BASE,
            stt.STT_QWEN_KEY,
            stt.STT_QWEN_GRACE_S,
            stt.STT_WHISPER_BASE,
            stt.STT_BASE,
            stt.ELEVENLABS_API_KEY,
            stt._CLIENT,
            stt._qwen_pause_bis,
            stt._qwen_future,
            stt._qwen_candidate,
            stt._whisper_ws,
            stt._pcm16k,
        ) = alt


def test_plausibles_parakeet_wartet_nicht_auf_qwen():
    release = threading.Event()

    def slow_qwen(_pcm, _keywords=""):
        release.wait(timeout=0.3)
        return _kandidat("Ich möchte zu Doktor Petsas.")

    def lauf(fake_lokal):
        started = time.perf_counter()
        text = stt.transcribe(BLOB, keywords="Petsas,Patrikis")
        elapsed = time.perf_counter() - started
        release.set()
        assert text == "Ich möchte zu Doktor Petsas."
        assert elapsed < 0.1
        assert fake_lokal.aufrufe

    _umgebung(lauf, qwen_candidate=slow_qwen, grace=0.25)


def test_auffaelliges_parakeet_uebernimmt_rechtzeitiges_qwen():
    def lauf(fake_lokal):
        text = stt.transcribe(BLOB, keywords="Röntgenbild")
        assert text == "Ein Röntgenbild."
        assert fake_lokal.aufrufe

    _umgebung(
        lauf,
        lokal_text="Ein Rhön Biepfeld.",
        qwen_candidate=lambda _pcm, _keywords="": _kandidat("Ein Röntgenbild."),
    )


def test_auffaelliges_parakeet_hat_harten_zusatzdeckel():
    def slow_qwen(_pcm, _keywords=""):
        time.sleep(0.12)
        return _kandidat("Ein Röntgenbild.")

    def lauf(_fake_lokal):
        started = time.perf_counter()
        text = stt.transcribe(BLOB, keywords="Röntgenbild")
        elapsed = time.perf_counter() - started
        assert text == "Bröntgempelt."
        assert elapsed < 0.08

    _umgebung(
        lauf,
        lokal_text="Bröntgempelt.",
        qwen_candidate=slow_qwen,
        grace=0.02,
    )


def test_qwen_ausfall_laesst_parakeet_sofort_stehen_und_pausiert():
    def kaputt(_pcm, _keywords=""):
        raise RuntimeError("qwen_timeout")

    def lauf(_fake_lokal):
        assert stt.transcribe(BLOB) == "Ich möchte zu Doktor Petsas."
        assert stt._qwen_future is not None
        stt._qwen_future.result(timeout=1)
        assert stt._qwen_pause_bis > time.time()

    _umgebung(lauf, qwen_candidate=kaputt)


def test_laufendes_qwen_staut_keinen_naechsten_zug():
    release = threading.Event()
    started = threading.Event()
    calls = []

    def slow_qwen(_pcm, _keywords=""):
        calls.append(1)
        started.set()
        release.wait(timeout=0.3)
        return _kandidat("Qwen.")

    def lauf(_fake_lokal):
        assert stt.transcribe(BLOB) == "Ich möchte zu Doktor Petsas."
        assert started.wait(timeout=0.2)
        assert stt.transcribe(BLOB) == "Ich möchte zu Doktor Petsas."
        release.set()
        assert len(calls) == 1

    _umgebung(lauf, qwen_candidate=slow_qwen)


def test_qwen_only_ohne_parakeet_bleibt_moeglich():
    def lauf(fake_lokal):
        assert stt.transcribe(BLOB) == "Nur Qwen."
        assert not fake_lokal.aufrufe

    _umgebung(
        lauf,
        stt_base="",
        qwen_candidate=lambda _pcm, _keywords="": _kandidat("Nur Qwen."),
    )


def test_kritischer_ziffernkonflikt_bleibt_bei_parakeet():
    assert not stt._qwen_darf_uebernehmen(
        "Meine Nummer ist null eins sieben sieben.",
        _kandidat("Meine Nummer ist null eins sieben acht."),
        True,
    )


def test_direkter_qwen_final_endpoint_traegt_nur_vocabular():
    fake = _FakeLokal("Direktes Qwen.")
    alt = (
        stt.STT_QWEN_FINAL_BASE,
        stt.STT_QWEN_KEY,
        stt._CLIENT,
    )
    try:
        stt.STT_QWEN_FINAL_BASE = "http://3060-test:8223"
        stt.STT_QWEN_KEY = "secret"
        stt._CLIENT = fake
        result = stt._qwen_final_message(b"\x00\x01" * 1000, "Petsas,Röntgen")
    finally:
        stt.STT_QWEN_FINAL_BASE, stt.STT_QWEN_KEY, stt._CLIENT = alt

    url, _files, data, kwargs = fake.aufrufe[0]
    assert url == "http://3060-test:8223/final"
    assert data == {"context": "Vokabular: Petsas, Röntgen."}
    assert kwargs["headers"]["X-Internal-Token"] == "secret"
    assert result["source"] == "qwen"


def test_qwen_url_und_health_anzeige():
    alt = (
        stt.STT_QWEN_BASE,
        stt.STT_QWEN_FINAL_BASE,
        stt.STT_WHISPER_BASE,
        stt.STT_BASE,
        stt._qwen_pause_bis,
    )
    try:
        stt.STT_QWEN_BASE = "https://paraqwenstt.pickadoc-tunnel.com/"
        stt.STT_QWEN_FINAL_BASE = ""
        stt.STT_WHISPER_BASE = "ws://whisper:8092"
        stt.STT_BASE = "http://parakeet:8212"
        stt._qwen_pause_bis = 0.0
        assert stt._qwen_ws_url() == (
            "wss://paraqwenstt.pickadoc-tunnel.com/stream"
        )
        assert stt.bereit()
        assert stt.engine_anzeige() == (
            "Parakeet (lokal) + Qwen3-ASR parallel (3060)"
        )
        stt._qwen_pause_bis = time.time() + 10
        assert stt.engine_anzeige() == "Parakeet (lokal, Qwen pausiert)"
    finally:
        (
            stt.STT_QWEN_BASE,
            stt.STT_QWEN_FINAL_BASE,
            stt.STT_WHISPER_BASE,
            stt.STT_BASE,
            stt._qwen_pause_bis,
        ) = alt
