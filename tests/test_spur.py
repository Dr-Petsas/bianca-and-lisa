"""Wächter-Spur (kern/spur.py, W-BK-3): jeder Wächter meldet seinen Eingriff,
der Dienst hängt die Liste additiv an Antwort + Protokoll. Offline."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kern import gespraech, spur, stille, unterbrechung, wiederholung
from kern.dienst import Dienst

S1 = "Ich habe drei Termine gefunden."
S2 = "Am Donnerstag um zehn Uhr wäre etwas frei."


def test_spur_grundlagen():
    sit: dict = {}
    spur.neu(sit)
    spur.merken(sit, "halbsatz-warte", "Ich hätte gerne einen")
    spur.merken(sit, "halbsatz-warte", "Ich hätte gerne einen")  # Doppel faellt weg
    spur.merken(sit, "barge-echo", "x" * 500)  # Detail wird gekappt
    eintraege = spur.abholen(sit)
    assert [e["w"] for e in eintraege] == ["halbsatz-warte", "barge-echo"]
    assert len(eintraege[1]["d"]) <= 160
    assert spur.abholen(sit) == [], "abholen leert die Spur"


def test_barge_eingang_und_fortsetzen_melden_sich():
    sit = {"messages": [{"role": "assistant", "content": f"{S1} {S2}"}]}
    karte = {"saetze": [S1, S2], "endenMs": [1000, 2500]}
    unterbrechung.merken(sit, url="/api/audio-stream/abc.wav", karte=karte,
                         text=f"{S1} {S2}")
    spur.neu(sit)
    assert unterbrechung.eingang(sit, "/api/audio-stream/abc.wav", 1200)
    text = unterbrechung.fortsetzen(sit, "Gern.", {}, gesagt="Moment mal kurz.")
    assert S2 in text
    namen = [e["w"] for e in spur.abholen(sit)]
    assert "barge-eingang" in namen and "barge-fortsetzen" in namen


def test_barge_abbruch_meldet_sich():
    sit = {"messages": [{"role": "assistant", "content": f"{S1} {S2}"}]}
    karte = {"saetze": [S1, S2], "endenMs": [1000, 2500]}
    unterbrechung.merken(sit, url="/api/audio-stream/abc.wav", karte=karte,
                         text=f"{S1} {S2}")
    spur.neu(sit)
    unterbrechung.eingang(sit, "/api/audio-stream/abc.wav", 500)
    text = unterbrechung.fortsetzen(sit, "Alles klar.", {}, gesagt="Stopp.")
    assert S2 not in text, "Abbruch verwirft den Rest"
    namen = [e["w"] for e in spur.abholen(sit)]
    assert "barge-abbruch" in namen


def test_wiederholung_meldet_variante_und_streichung():
    frage = "Wie ist Ihre Telefonnummer?"
    sit = {"frageForm": {}}
    spur.neu(sit)
    out = wiederholung.pruefen(
        sit, frage, frueher=[frage],
        frage_id="telefon", frage_kern=r"telefonnummer|nummer",
        varianten={"telefon": ("Unter welcher Nummer erreichen wir Sie?",)},
    )
    assert out == "Unter welcher Nummer erreichen wir Sie?"
    langsatz = ("Ich schaue gern im Kalender nach einem passenden Termin "
                "für Sie, das dauert nur einen kleinen Moment.")
    out2 = wiederholung.pruefen(sit, langsatz, frueher=[langsatz])
    assert out2 == ""
    namen = [e["w"] for e in spur.abholen(sit)]
    assert "wiederholung-variante" in namen
    assert "wiederholung-gestrichen" in namen


def test_stille_stups_meldet_sich():
    sit: dict = {}
    spur.neu(sit)
    assert stille.stups_zaehlen(sit) == 1
    eintraege = spur.abholen(sit)
    assert eintraege and eintraege[0]["w"] == "stille-stups"


def test_talk_floor_meldet_sich():
    sit: dict = {}
    spur.neu(sit)
    route = gespraech.routen(sit, "Haben Sie gestern das Fußballspiel gesehen?")
    assert route["floor"] in ("talk", "blended")
    namen = [e["w"] for e in spur.abholen(sit)]
    assert "talk-floor" in namen


def test_dienst_antwort_traegt_waechter_und_frage():
    d = Dienst(name="test",
               start_fn=lambda sit: {"text": "Hallo."},
               turn_fn=lambda sit, text, melde=None, vorab=None: {"text": "Alles klar."})
    d.stimme_stream = lambda text, karte=None: ("", 0.0)  # offline: kein TTS
    sit = {"sammler": {"frage": "name", "modus": "buchen"}}
    spur.neu(sit)
    spur.merken(sit, "halbsatz-fuge", "Ich hätte gerne einen Termin")
    out = d.json_antwort(sit, art="turn", text_in="Ich hätte gerne einen Termin")
    assert out["waechter"] == [{"w": "halbsatz-fuge", "d": "Ich hätte gerne einen Termin"}]
    assert out["frage"] == "name" and out["modus"] == "buchen"
    assert sit.get("_spur") is None or sit.get("_spur") == []


def test_dienst_zug_stream_haelt_halbsatz_und_fuegt():
    d = Dienst(name="test",
               start_fn=lambda sit: {"text": "Hallo."},
               turn_fn=lambda sit, text, melde=None, vorab=None: {"text": f"OK: {text}"})
    d.stimme_stream = lambda text, karte=None: ("", 0.0)
    sit: dict = {}
    zeilen = list(d.zug_stream(sit, art="turn", text_in="Ich hätte gerne einen"))
    assert any('"warte"' in z for z in zeilen), zeilen
    zeilen2 = list(d.zug_stream(sit, art="turn", text_in="Termin für nächste Woche."))
    import json as _json
    reply = next(_json.loads(z) for z in zeilen2 if '"reply"' in z)
    assert reply["textIn"].startswith("Ich hätte gerne einen Termin")
    namen = [e["w"] for e in reply["waechter"]]
    assert "halbsatz-fuge" in namen
    # die warte-Spur des VORIGEN Zugs klebt nicht am neuen:
    assert "halbsatz-warte" not in namen


if __name__ == "__main__":
    fehler = 0
    for name in sorted(n for n in dir() if n.startswith("test_")):
        try:
            globals()[name]()
            print(f"gruen: {name}")
        except AssertionError as e:
            fehler += 1
            print(f"ROT:   {name} — {e}")
    sys.exit(1 if fehler else 0)
