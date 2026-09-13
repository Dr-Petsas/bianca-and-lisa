"""Live-Probe im Container: greifen W-FRAGE-GATE, W-HIRN-GATE, W-DIKTAT-FERTIG?

Nur lesend/rechnend - kein Netz, kein Kalender, kein Schreiben.
    docker exec -w /app telefonki-bianca-1 python tools/_probe_gate_live.py
"""

from bianca import besuchsgrund, buchstaben, gehirn
from kern import frage_gate


def main() -> None:
    print("frage_gate modus:", frage_gate.modus())

    sit = {"sammler": {"nachname": "Rateike", "vorname": "Maximilian", "modus": "buchen", "frage": "wunsch"}}
    roh = "Moechten Sie die Zahnreinigung gleich mitbuchen? Und wie ist Ihr Vorname?"
    text, feld, belegt = frage_gate.saeubern(sit, roh)
    print("roh        :", roh)
    print("gesaeubert :", (text.strip() or "(leer)"), "| gestrichen:", feld or "-", "belegt:", belegt)
    text2, feld2, _ = frage_gate.saeubern(sit, "Ihr Vorname ist Maximilian, richtig?")
    print("rueckfrage :", text2, "| gestrichen:", feld2 or "-")

    lauf = {"tenant": {"praxisName": "Testpraxis",
                       "calendars": [{"id": "c1", "name": "Doktor Michael Petsas"}],
                       "defaultCalendarId": "c1"}}
    s = gehirn.sammler(lauf)
    s.update({"modus": "buchen", "warSchonMal": True, "nachname": "Rateike",
              "buchstabiert": True, "vorname": "Maximilian", "vornameQuelle": "akte",
              "arzt": {"typ": "genannt", "calendarId": "c1",
                       "calendarName": "Doktor Michael Petsas"}})
    fid = gehirn.naechste_frage(lauf)
    print("kartei-vorname frage:", fid, "->", gehirn.vorname_check_frage(s))
    s["vornameQuelle"] = "gesagt"
    print("gesagter vorname    :", gehirn.naechste_frage(lauf))

    print("diktat fertig   :", buchstaben.deute("R, A, T, E, I, K, E, fertig."))
    print("diktat fuellwort:", buchstaben.deute("Rateike, aufstabiert es das R-A-T-E-I-K-E."))
    print("ja nachgestellt :", gehirn.ist_ja("Haben wir doch schon gesagt, ja."))
    print("vergewisserung  :", gehirn.ist_ja("Sie tragen das ein, ja?"))

    katalog = [{"id": "kfo", "name": "KFO Besprechung", "duration": 30},
               {"id": "kontrolle", "name": "KCH Kontrolluntersuchung", "duration": 30}]
    _, vm = besuchsgrund.deute({}, "Ich habe schiefe Zehen, ich moechte die gerade haben.",
                               katalog=katalog)
    print("schiefe zehen   :", (vm or {}).get("name"))


if __name__ == "__main__":
    main()
