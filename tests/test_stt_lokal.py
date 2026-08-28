"""kern/stt.py: lokaler Conformer-Container OHNE ElevenLabs-Rueckfall.

Vertrag (Chef 28.08.2026): Ist STT_BASE gesetzt, transkribiert NUR der
lokale Container auf der 5090. Schlaegt er fehl, fliegt RuntimeError —
es gibt KEINEN stillen Rueckfall auf ElevenLabs Scribe.
"""

from __future__ import annotations

import kern.stt as stt


class _Antwort:
    def __init__(self, status_code: int = 200, daten: dict | None = None):
        self.status_code = status_code
        self._daten = daten or {}

    def json(self):
        return self._daten


class _FakeLokal:
    def __init__(self, antwort: _Antwort):
        self.antwort = antwort
        self.aufrufe: list[tuple[str, dict]] = []

    def post(self, url, files=None, **kw):
        self.aufrufe.append((url, files or {}))
        return self.antwort


def _mit_lokal(fake: _FakeLokal, fn) -> None:
    alt = (stt.STT_BASE, stt._CLIENT)
    stt.STT_BASE = "http://stt-test:8100"
    stt._CLIENT = fake
    # ElevenLabs-Waechter: httpx.post im Modul wuerde live rausgehen — im
    # Test durch Alarm ersetzen.
    alt_post = stt.httpx.post

    def _alarm(*a, **kw):
        raise AssertionError("ElevenLabs angefasst, obwohl STT_BASE gesetzt ist (kein Fallback!)")

    stt.httpx.post = _alarm
    try:
        fn()
    finally:
        (stt.STT_BASE, stt._CLIENT) = alt
        stt.httpx.post = alt_post


BLOB = b"x" * 2000


def test_lokal_transkribiert_ohne_elevenlabs():
    fake = _FakeLokal(_Antwort(200, {"text": "  Ich   haette gern einen Termin. "}))

    def lauf():
        text = stt.transcribe(BLOB, mime="audio/webm", name="turn.webm")
        assert text == "Ich haette gern einen Termin."
        url, files = fake.aufrufe[0]
        assert url == "http://stt-test:8100/transcribe"
        assert files["file"][0] == "turn.webm" and files["file"][2] == "audio/webm"

    _mit_lokal(fake, lauf)


def test_lokal_fehler_wirft_statt_zurueckzufallen():
    fake = _FakeLokal(_Antwort(500, {}))

    def lauf():
        try:
            stt.transcribe(BLOB)
            raise AssertionError("RuntimeError erwartet")
        except RuntimeError as e:
            assert "stt_lokal_http_500" in str(e)

    _mit_lokal(fake, lauf)


def test_kyrillische_halluzination_wird_verworfen():
    fake = _FakeLokal(_Antwort(200, {"text": "Продолжение следует"}))

    def lauf():
        assert stt.transcribe(BLOB) == ""

    _mit_lokal(fake, lauf)


def test_winzige_blobs_gehen_gar_nicht_erst_raus():
    fake = _FakeLokal(_Antwort(200, {"text": "sollte nie ankommen"}))

    def lauf():
        assert stt.transcribe(b"x" * 100) == ""
        assert not fake.aufrufe, "unter 800 Bytes wird gar nicht angefragt"

    _mit_lokal(fake, lauf)


def test_bereit_mit_stt_base_auch_ohne_key():
    alt = (stt.STT_BASE, stt.ELEVENLABS_API_KEY)
    try:
        stt.STT_BASE = "http://stt-test:8100"
        stt.ELEVENLABS_API_KEY = ""
        assert stt.bereit(), "STT_BASE allein muss reichen"
        stt.STT_BASE = ""
        assert not stt.bereit()
    finally:
        (stt.STT_BASE, stt.ELEVENLABS_API_KEY) = alt


if __name__ == "__main__":
    test_lokal_transkribiert_ohne_elevenlabs()
    test_lokal_fehler_wirft_statt_zurueckzufallen()
    test_kyrillische_halluzination_wird_verworfen()
    test_winzige_blobs_gehen_gar_nicht_erst_raus()
    test_bereit_mit_stt_base_auch_ohne_key()
    print("test_stt_lokal: alle Faelle bestanden")
