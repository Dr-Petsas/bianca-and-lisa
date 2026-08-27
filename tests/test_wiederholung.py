"""Wiederholungs-Wächter (kern/wiederholung.py, Chef 27.08.2026):
"ich will nie wieder doppelte telefonnummer oder behandler abfragen hören."

Dieselbe Pflichtfrage nie zweimal wortgleich — beim zweiten Mal kommt die
nächste Formulierung (gehirn.FRAGE_VARIANTEN), andere wortgleiche Frage-/
Langsätze fliegen. telefon_check, Readbacks und Kurzquittungen bleiben
unangetastet. Offline, ohne LLM.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bianca import agent as bianca_agent
from bianca import gehirn
from kern import gespraech, wiederholung


TELEFON_FRAGE = "Und unter welcher Handynummer erreichen wir Sie?"


def _sit() -> dict:
    return {"tenant": {"praxisName": "Testpraxis"}, "messages": []}


def _buchungs_sit(frage: str = "telefon") -> dict:
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "phase": "", "frage": frage,
        "warSchonMal": False, "grund": "Kontrolle", "wunsch": {},
        "vorname": "Anna", "nachname": "Meier", "buchstabiert": True,
    })
    return sit


# ---------------------------------------------------------------------------
# Kern: pruefen()
# ---------------------------------------------------------------------------

def test_wiederholte_frage_bekommt_variante():
    sit = _sit()
    raus = wiederholung.pruefen(
        sit, f"Alles klar. {TELEFON_FRAGE}",
        frueher=[f"Gern. {TELEFON_FRAGE}"],
        frage_id="telefon", frage_kern=r"nummer|handy|telefon",
        varianten=gehirn.FRAGE_VARIANTEN,
    )
    assert TELEFON_FRAGE not in raus, "nie zweimal wortgleich"
    assert "andynummer" in raus, "die Frage muss hoerbar bleiben (Kern-Wort)"
    assert raus.startswith("Alles klar.")


def test_dritte_wiederholung_nimmt_naechste_variante():
    sit = _sit()
    v1 = gehirn.FRAGE_VARIANTEN["telefon"][0]
    raus = wiederholung.pruefen(
        sit, f"Verstehe. {v1}",
        frueher=[f"Gern. {v1}", f"Okay. {TELEFON_FRAGE}"],
        frage_id="telefon", frage_kern=r"nummer|handy|telefon",
        varianten=gehirn.FRAGE_VARIANTEN,
    )
    assert v1 not in raus and TELEFON_FRAGE not in raus
    assert "andynummer" in raus


def test_alle_varianten_verbrannt_streicht_die_frage():
    sit = _sit()
    formen = list(gehirn.FRAGE_VARIANTEN["telefon"])
    raus = wiederholung.pruefen(
        sit, f"Gut. {TELEFON_FRAGE}",
        frueher=[TELEFON_FRAGE] + formen,
        frage_id="telefon", frage_kern=r"nummer|handy|telefon",
        varianten=gehirn.FRAGE_VARIANTEN,
    )
    assert raus == "Gut.", "alle Formen gehoert -> streichen, Eskalation uebernimmt"


def test_telefon_check_bleibt_unangetastet():
    sit = _sit()
    text = "Ich wiederhole die Nummer: null eins sieben sieben, sechs null null. Stimmt das so?"
    raus = wiederholung.pruefen(
        sit, text, frueher=[text],
        frage_id="telefon_check", frage_kern=r"nummer|stimmt",
        varianten=gehirn.FRAGE_VARIANTEN,
    )
    assert raus == text, "Rueckbestaetigung bleibt IMMER deterministisch"


def test_ziffern_readback_bleibt():
    sit = _sit()
    satz = "Ich habe die null eins sieben sieben, sechs null null, eins eins notiert."
    raus = wiederholung.pruefen(sit, satz, frueher=[satz])
    assert raus == satz, "Nummern-Readbacks werden nie gestrichen"


def test_kurzquittung_darf_sich_wiederholen():
    sit = _sit()
    raus = wiederholung.pruefen(
        sit, "Alles klar. Einen Moment bitte.",
        frueher=["Alles klar. Einen Moment bitte."],
    )
    assert "Alles klar." in raus, "natuerliche Quittungen bleiben"


def test_wiederholter_langsatz_fliegt():
    sermon = ("Die professionelle Zahnreinigung dauert bei uns ungefähr eine "
              "Stunde und kostet je nach Aufwand zwischen achtzig und hundert Euro.")
    sit = _sit()
    raus = wiederholung.pruefen(sit, f"{sermon} Passt Ihnen Donnerstag?", frueher=[sermon])
    assert sermon not in raus, "einmal gesagt reicht"
    assert "Donnerstag" in raus


def test_variante_traegt_immer_die_kernwoerter():
    import re
    for fid, formen in gehirn.FRAGE_VARIANTEN.items():
        kern = bianca_agent._FRAGE_KERN.get(fid)
        assert kern, f"{fid} braucht ein Kern-Muster"
        for form in formen:
            assert re.search(kern, form, re.I), f"Variante ohne Kern-Wort: {fid}: {form}"


# ---------------------------------------------------------------------------
# Einhaengung: _nachbessern (LLM-Pfad) — Anker + Waechter zusammen
# ---------------------------------------------------------------------------

def test_anker_wiederholung_wird_umformuliert():
    """Live 27.08.: 'Wie ist Ihre Handynummer?' kam dreimal in Folge. Der
    Anker haengt die kanonische Frage an, der Waechter tauscht sie gegen
    eine Variante — die Frage bleibt hoerbar, aber nie im selben Wortlaut."""
    sit = _buchungs_sit()
    frage = bianca_agent._kanonische_frage(sit, "telefon")
    sit["messages"] = [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": f"Gern. {frage}"},
        {"role": "user", "content": "Moment, mein Hund bellt gerade."},
    ]
    raus = bianca_agent._nachbessern(sit, "Kein Problem.", floor=gespraech.ZURUECK)
    assert frage not in raus, "nie zweimal wortgleich"
    assert "andynummer" in raus, "aber die offene Frage bleibt hoerbar"


def test_maschinen_frage_wird_beim_zweiten_mal_umformuliert():
    """Maschinen-Pfad: der Fluss fragt die noch offene Frage erneut (Anrufer
    hat erst etwas anderes beantwortet) — zweite Form statt Wortgleichheit."""
    sit = _buchungs_sit()
    sit["messages"] = [
        {"role": "system", "content": "..."},
        {"role": "assistant", "content": f"Danke. {TELEFON_FRAGE}"},
    ]
    raus = bianca_agent._wiederholungs_wache(sit, f"Alles klar. {TELEFON_FRAGE}")
    assert TELEFON_FRAGE not in raus
    assert "andynummer" in raus


def test_behandler_frage_nie_doppelt():
    sit = _buchungs_sit(frage="arzt")
    arzt_frage = "Wissen Sie noch, bei welchem Behandler Sie zuletzt waren?"
    sit["messages"] = [
        {"role": "system", "content": "..."},
        {"role": "assistant", "content": arzt_frage},
    ]
    raus = bianca_agent._wiederholungs_wache(sit, arzt_frage)
    assert raus and raus != arzt_frage, "Behandler-Frage nie wortgleich doppelt"
    assert "ehandler" in raus


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
    print("test_wiederholung: alle gruen")
