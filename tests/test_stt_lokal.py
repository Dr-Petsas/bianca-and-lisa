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


def test_kurze_englische_parakeet_formen_werden_verworfen():
    for gehoert in (
        "Yeah.",
        "Yep!",
        "Yes.",
        "No.",
        "Nope.",
        "Nine.",
        "Hello?",
        "Correct.",
        "Stop.",
    ):
        fake = _FakeLokal(_Antwort(200, {"text": gehoert}))

        def lauf():
            assert stt.transcribe(BLOB) == ""

        _mit_lokal(fake, lauf)


def test_englische_stille_halluzinationen_werden_verworfen():
    faelle = (
        "I'm sorry.",
        "I am sorry.",
        "Sorry.",
        "Thank you.",
        "Thanks for watching.",
        "Please subscribe.",
        "I would like an appointment.",
        "I am Michael.",
        "My name is Michael.",
        "Good morning, Mister Smith.",
        "Teen sucks.",
        "Tuesday morning.",
        # Live Thaler 28.09.2026, Anruf 8e68db99…:
        "Damn it.",
        "Queen Service.",
        "I need 2 appointments.",
    )
    for gehoert in faelle:
        fake = _FakeLokal(_Antwort(200, {"text": gehoert}))

        def lauf():
            assert stt.transcribe(BLOB) == ""

        _mit_lokal(fake, lauf)


def test_sprachwache_behaelt_deutsche_saetze_und_eigennamen():
    faelle = (
        "Sorry, ich brauche einen Termin.",
        "Dienstags nicht.",
        "Ich möchte online einen Termin buchen.",
        "Mein Nachname ist Smith.",
        "Okay, danke.",
        "Bitte ja.",
        "Zahnreinigung.",
        "Kontrolle.",
        "Schmerzen.",
        "Kundenservice.",
        "Müller Service.",
        "Alice Biberci.",
        "Ja man.",
    )
    for gehoert in faelle:
        fake = _FakeLokal(_Antwort(200, {"text": gehoert}))

        def lauf():
            assert stt.transcribe(BLOB) == gehoert

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
    assert kw == ["Petsas", "Nikolaou", "Patrikis"], kw
    # Marker-Keywords (Heads-up etc.) duerfen NIE dabei sein — Patiententelefon.
    assert not {k.lower() for k in kw} & {"heads-up", "headsup", "teleskopkrone", "kons"}


def test_praxisname_ist_tenant_hotword_ohne_generische_woerter():
    tenant = {
        "praxisName": "Thaler Zahnmedizin",
        "praxisNameMelde": "Praxis Thaler Zahnmedizin",
        "calendars": [{"id": "1", "name": "Frau Schmidt"}],
    }
    kw = tenants.stt_keywords(tenant)
    assert kw == ["Thaler", "Schmidt"], kw


def test_thaler_alias_ist_nur_mit_tenant_hotword_aktiv():
    faelle = {
        "Hier ist Ttola Zahnmedizin": "Hier ist Thaler Zahnmedizin",
        "Otala.": "Thaler.",
        "Hotala": "Thaler",
        "Oh, Tala.": "Oh, Thaler.",
    }
    for gehoert, erwartet in faelle.items():
        fake = _FakeLokal(_Antwort(200, {"text": gehoert}))

        def lauf():
            assert stt.transcribe(BLOB, keywords="Thaler") == erwartet

        _mit_lokal(fake, lauf)

    # Die weit gefassten Realvarianten sind ausschließlich beim passenden
    # Mandanten aktiv. Insbesondere "Tala" darf global kein Alias sein.
    fake2 = _FakeLokal(_Antwort(200, {"text": "Oh, Tala."}))

    def ohne_marker():
        assert stt.transcribe(BLOB, keywords="Petsas") == "Oh, Tala."

    _mit_lokal(fake2, ohne_marker)


def test_thaler_fachhotwords_kommen_aus_dem_mandanten():
    tenant = tenants.laden("thaler")
    kw = tenants.stt_keywords(tenant)
    assert "Thaler" in kw
    assert "Röntgenbild" in kw
    assert "Röntgenbilder" in kw
    assert "Sprechstundenhilfe" in kw


def test_thaler_live_hoerfehler_werden_konservativ_korrigiert():
    from stt_serve.postcorrect import correct_transcript

    kw = ["Thaler", "Röntgenbild", "Röntgenbilder", "Sprechstundenhilfe"]
    faelle = {
        "Ich bräuchte mein Rückenbild bitte.": "Ich bräuchte mein Röntgenbild bitte.",
        "Ich brauche mein Rentenbild für den Zahnarzt.": "Ich brauche mein Röntgenbild für den Zahnarzt.",
        "Ein Rhöngbild.": "Ein Röntgenbild.",
        "Bitte den Räumenbild Herr Fox.": "Bitte den Röntgenbild Herr Fox.",
        "Röntgenbulder faxen zum Zahnarzt Doktor Esser.": "Röntgenbilder faxen zum Zahnarzt Doktor Esser.",
        "Ja, ich brauche eine Spress von der Hilfe.": "Ja, ich brauche eine Sprechstundenhilfe.",
        "Wild einer Sprechstunde Hilfesprecher.": "Wild einer Sprechstundenhilfe.",
    }
    for gehoert, erwartet in faelle.items():
        text, ersetzt = correct_transcript(gehoert, kw)
        assert text == erwartet, (gehoert, text)
        assert ersetzt, gehoert

    # Die starken Aliase gelten ausschließlich mit ihrem Fach-Hotword.
    for gehoert in ("Rückenbild.", "Spress von der Hilfe."):
        text, _ = correct_transcript(gehoert, ["Thaler"])
        assert text == gehoert, (gehoert, text)

    # Plausible Personennamen niemals blind zu einem Dokument umschreiben.
    text, ersetzt = correct_transcript("Brent Campbellt.", kw)
    assert text == "Brent Campbellt."
    assert not ersetzt


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


def test_namenszug_bekommt_nur_tafel_hotwords():
    from bianca import buchstaben

    tafel = set(buchstaben.stt_hotwords())
    assert "Cäsar" in tafel or "Caesar" in tafel or "Anton" in tafel
    sit = {
        "tenant": {
            "clientId": "MEe4ZQHEzOPzLcexyhdT",
            "behandler": "Dr. Petsas",
            "calendars": [{"id": "1", "name": "Dr. Petsas"}],
        },
        "sammler": {"frage": "buchstabieren"},
        "qwenHotwords": ["Röntgenbild"],
    }
    kw = stt.keywords_fuer_sitzung(sit)
    woerter = {w.strip() for w in kw.split(",") if w.strip()}
    assert "Petsas" not in woerter
    assert "Röntgenbild" not in woerter
    assert woerter <= tafel
    assert "Anton" in woerter

    sit["sammler"]["frage"] = "wunsch"
    kw = stt.keywords_fuer_sitzung(sit)
    woerter = {w.strip() for w in kw.split(",") if w.strip()}
    assert "Petsas" in woerter
    assert "Röntgenbild" in woerter
    assert "Uhr" in woerter and "dreißig" in woerter


def test_nummernzug_bekommt_nur_ziffern_hotwords():
    from bianca import telefon as tel

    sit = {
        "tenant": {
            "clientId": "MEe4ZQHEzOPzLcexyhdT",
            "behandler": "Dr. Petsas",
            "calendars": [{"id": "1", "name": "Dr. Petsas"}],
        },
        "sammler": {"frage": "telefon"},
        "qwenHotwords": ["Röntgenbild"],
    }
    kw = stt.keywords_fuer_sitzung(sit)
    woerter = {w.strip() for w in kw.split(",") if w.strip()}
    assert "Petsas" not in woerter
    assert "Röntgenbild" not in woerter
    assert "null" in woerter and "neun" in woerter
    assert "nein" not in woerter

    sit["sammler"]["frage"] = "telefon_check"
    kw = stt.keywords_fuer_sitzung(sit)
    check = [w.strip() for w in kw.split(",") if w.strip()]
    assert check[0] == "ja"
    assert "nein" in check and "neun" in check
    assert "nine" not in check
    assert "Petsas" not in check
    assert set(check) == set(tel.stt_hotwords(check=True))

    sit["sammler"] = {"frage": "wunsch", "telefonTeil": "0177"}
    kw = stt.keywords_fuer_sitzung(sit)
    woerter = {w.strip() for w in kw.split(",") if w.strip()}
    assert "Petsas" not in woerter
    assert "null" in woerter


def test_namens_sicherung_default_nur_mit_client_id():
    from kern.tenants import namens_sicherung

    assert namens_sicherung({}, "buchstabierSegmenteTrennen") is False
    assert namens_sicherung(
        {"clientId": "abc"}, "buchstabierSegmenteTrennen"
    ) is True
    assert namens_sicherung(
        {"clientId": "abc", "buchstabierSegmenteTrennen": False},
        "buchstabierSegmenteTrennen",
    ) is False
    assert namens_sicherung(
        {"buchstabierSegmenteTrennen": True},
        "buchstabierSegmenteTrennen",
    ) is True


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
    test_kurze_englische_parakeet_formen_werden_deutsch_normalisiert()
    test_tenant_keywords_sind_behandler_nachnamen()
    test_praxisname_ist_tenant_hotword_ohne_generische_woerter()
    test_thaler_alias_ist_nur_mit_tenant_hotword_aktiv()
    test_thaler_fachhotwords_kommen_aus_dem_mandanten()
    test_thaler_live_hoerfehler_werden_konservativ_korrigiert()
    test_postcorrect_kopie_fixt_behandler_hoerfehler()
    test_lokal_fehler_wirft_statt_zurueckzufallen()
    test_kyrillische_halluzination_wird_verworfen()
    test_winzige_blobs_gehen_gar_nicht_erst_raus()
    test_namenszug_bekommt_nur_tafel_hotwords()
    test_nummernzug_bekommt_nur_ziffern_hotwords()
    test_namens_sicherung_default_nur_mit_client_id()
    test_bereit_mit_stt_base_auch_ohne_key()
    print("test_stt_lokal: alle Faelle bestanden")
