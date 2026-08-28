"""kern/stt.py: lokaler Parakeet-Container OHNE ElevenLabs-Rueckfall.

Vertrag (Chef 28.08.2026): Ist STT_BASE gesetzt, transkribiert NUR der
lokale Container auf der 5090 (Claras bewaehrte Parakeet-Strecke).
Schlaegt er fehl, fliegt RuntimeError — es gibt KEINEN stillen Rueckfall
auf ElevenLabs Scribe. Behandler-Keywords gehen als Hotwords mit.
"""

from __future__ import annotations

import kern.stt as stt
from kern import tenants


class _Antwort:
    def __init__(self, status_code: int = 200, daten: dict | None = None):
        self.status_code = status_code
        self._daten = daten or {}

    def json(self):
        return self._daten


class _FakeLokal:
    def __init__(self, antwort: _Antwort):
        self.antwort = antwort
        self.aufrufe: list[tuple[str, dict, dict]] = []

    def post(self, url, files=None, data=None, **kw):
        self.aufrufe.append((url, files or {}, data or {}))
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
        url, files, _ = fake.aufrufe[0]
        assert url == "http://stt-test:8100/transcribe"
        assert files["file"][0] == "turn.webm" and files["file"][2] == "audio/webm"

    _mit_lokal(fake, lauf)


def test_keywords_gehen_als_hotwords_mit():
    fake = _FakeLokal(_Antwort(200, {"text": "Termin bei Petsas"}))

    def lauf():
        stt.transcribe(BLOB, keywords="Petsas,Nikolaou,Patrikis")
        _, _, data = fake.aufrufe[0]
        assert data.get("keywords") == "Petsas,Nikolaou,Patrikis"

    _mit_lokal(fake, lauf)


def test_tenant_keywords_sind_behandler_nachnamen():
    tenant = {
        "behandler": "Dr. Petsas",
        "calendars": [
            {"id": "1", "name": "Dr. Nikolaou"},
            {"id": "2", "name": "Dr. Patrikis"},
            {"id": "3", "name": "Dr. Petsas"},
        ],
    }
    kw = tenants.stt_keywords(tenant)
    assert {"Petsas", "Nikolaou", "Patrikis"} <= set(kw), kw
    assert "Peter" in kw and "Kontrolle" in kw
    assert "Tzannis" in kw and "Füllung" in kw
    # Marker-Keywords (Heads-up etc.) duerfen NIE dabei sein — Patiententelefon.
    assert not {k.lower() for k in kw} & {"heads-up", "headsup", "teleskopkrone", "kons"}


def test_postcorrect_kopie_fixt_behandler_hoerfehler():
    # Die Kopie von Claras stt_postcorrect im Container-Ordner: Anlaut-
    # Verwechslung P/B ("Betsas") und Vokal-Garble ("Patrikus") muessen auf
    # die echten Behandler snappen; unbeteiligte Woerter bleiben stehen.
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stt_serve"))
    try:
        from postcorrect import correct_transcript
    finally:
        sys.path.pop(0)
    kw = ["Petsas", "Nikolaou", "Patrikis"]
    text, repl = correct_transcript("Ich moechte zu Doktor Betsas bitte", kw)
    assert "Petsas" in text and repl, (text, repl)
    text2, _ = correct_transcript("Verbinden Sie mich mit Doktor Patrikus", kw)
    assert "Patrikis" in text2, text2
    text3, repl3 = correct_transcript("Ich haette gern einen Termin am Montag", kw)
    assert text3 == "Ich haette gern einen Termin am Montag" and not repl3


def test_postcorrect_v7_buchstabieren_und_tacken():
    """Clara V7: Buchstabier-Kette + Bianca-Live 'welcher Tacken'."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stt_serve"))
    try:
        from postcorrect import buchstabiertes_zusammenziehen, correct_transcript
    finally:
        sys.path.pop(0)
    text, repl = buchstabiertes_zusammenziehen("T-Z-A-N-N-I-S")
    assert text == "Tzannis" and repl
    text2, _ = buchstabiertes_zusammenziehen(
        "T wie Theodor, Z wie Zeppelin, A wie Anton, N wie Nordpol, N wie Nordpol, I wie Ida, S wie Siegfried"
    )
    assert text2 == "Tzannis", text2
    text3, repl3 = correct_transcript("Ich wuerde gerne wissen, welcher Tacken.", [])
    assert "welcher Tag" in text3 and "Tacken" not in text3 and repl3
    # y/i + Anlaut: Zanis (0.833) greift auf Tzannis (Clara-V7-Schwelle 0.82).
    text4, repl4 = correct_transcript("Termin fuer Frau Zanis", ["Tzannis"])
    assert "Tzannis" in text4 and repl4
    text5, repl5 = correct_transcript("Ich brauche eine Zülung", [])
    assert "Füllung" in text5 and repl5
    # Clara-Kommando-Phrasen bleiben AUS ohne Marker.
    text6, _ = correct_transcript("Hands up bitte", [])
    assert "Heads-up" not in text6


def test_halluzination_filter_clara_v7():
    """Atem-/Untertitel-Phantome weg, echte Telefon-Antworten bleiben."""
    assert stt._sauber("Thank you.") == ""
    assert stt._sauber("Thank you, Dr.") == ""
    assert stt._sauber("Продолжение следует") == ""
    assert stt._sauber("Ja, ja, ja") == ""
    assert stt._sauber("Ja") == "Ja"
    assert stt._sauber("Tschüss") == "Tschüss"
    assert stt._sauber("Vielen Dank") == "Vielen Dank"
    assert stt._sauber("Ich hätte gern einen Termin") == "Ich hätte gern einen Termin"


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
    test_keywords_gehen_als_hotwords_mit()
    test_tenant_keywords_sind_behandler_nachnamen()
    test_postcorrect_kopie_fixt_behandler_hoerfehler()
    test_postcorrect_v7_buchstabieren_und_tacken()
    test_halluzination_filter_clara_v7()
    test_lokal_fehler_wirft_statt_zurueckzufallen()
    test_kyrillische_halluzination_wird_verworfen()
    test_winzige_blobs_gehen_gar_nicht_erst_raus()
    test_bereit_mit_stt_base_auch_ohne_key()
    print("test_stt_lokal: alle Faelle bestanden")
