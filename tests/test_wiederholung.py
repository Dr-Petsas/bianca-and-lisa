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


def test_wache_restored_nie_das_original():
    """W-REPEAT 01.09.2026: `or text` holte früher die wortgleiche Frage zurück."""
    sit = _buchungs_sit("telefon")
    sit["messages"] = [
        {"role": "assistant", "content": TELEFON_FRAGE},
    ]
    # Varianten verbrennen
    sit["frageForm"] = {"telefon": 99}
    formen = list(gehirn.FRAGE_VARIANTEN["telefon"])
    sit["messages"] = [{"role": "assistant", "content": x} for x in [TELEFON_FRAGE] + formen]
    raus = bianca_agent._wiederholung_oder_presence(sit, TELEFON_FRAGE)
    assert raus != TELEFON_FRAGE
    assert "noch dran" in raus.casefold() or "andynummer" in raus


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


def test_slot_angebot_wird_nie_gestrichen():
    """W-ANGEBOT-BLEIBT (A5, 17.09.2026), live 66913eb8 Zug 19: die wortgleiche
    Slot-Liste flog, gesprochen wurde nur 'Welcher davon passt Ihnen?'."""
    angebot = ("Frei ist am Montag, den siebten Dezember um zwölf Uhr; "
               "am Dienstag, den achten Dezember um halb neun; "
               "oder am Mittwoch, den neunten Dezember um vierzehn Uhr.")
    sit = _sit()
    raus = wiederholung.pruefen(
        sit, f"Alles klar. {angebot} Welcher davon passt Ihnen?",
        frueher=[f"{angebot} Welcher davon passt Ihnen?"],
    )
    assert angebot in raus, "Angebots-Saetze sind Fakten — der Anrufer muss waehlen koennen"
    assert "Welcher davon passt Ihnen?" in raus, "die Wahlfrage bleibt beim Angebot"


def test_termin_readback_wird_nie_gestrichen():
    for satz in [
        "Dann halte ich fest: Donnerstag um halb zehn bei Doktor Petsas zur Kontrolle.",
        "Ihr nächster Termin ist am dritten Oktober um neun Uhr.",
        "Genau dann ist leider nichts frei. Frei wäre morgen um dreizehn Uhr dreißig.",
    ]:
        sit = _sit()
        raus = wiederholung.pruefen(sit, satz, frueher=[satz])
        assert raus == satz, satz


def test_sermon_ohne_terminfakt_fliegt_weiterhin():
    """Gegenprobe: 'Stunde'/'Euro' sind keine Termin-Fakten — der Langsatz
    ohne Wochentag/Monat/Uhr wird weiterhin entdoppelt."""
    sermon = ("Die Aufhellung dauert bei uns ungefähr eine Stunde länger und "
              "wird vom Doktor vorher in Ruhe angeschaut und besprochen.")
    sit = _sit()
    raus = wiederholung.pruefen(sit, f"{sermon} Möchten Sie das?", frueher=[sermon])
    assert sermon not in raus


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


def test_hallo_vorab_wird_vom_waechter_gestrichen():
    """Live 08.09.2026: „Ah, Herr Petsas. Wir kennen uns noch nicht.“
    ging als Vorab raus — der Wächter sah nur die LLM-Antwort (kurz, ohne
    Fragezeichen = Quittung) und ließ den Hallo jeden Zug erneut durch."""
    hallo = "Ah, Herr Petsas. Wir kennen uns noch nicht. Ich bin die Neue!"
    sit = _sit()
    wiederholung.gesagt_merken(sit, hallo)
    raus = wiederholung.pruefen(
        sit, hallo, frueher=[], auch_kurz=True,
    )
    assert raus == "", "schon gesprochener Hallo darf nicht nochmal raus"
    # Ohne auch_kurz bleiben kurze Sätze Quittungen (Alt-Verhalten).
    raus2 = wiederholung.pruefen(sit, hallo, frueher=[hallo])
    assert "Herr Petsas" in raus2


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
