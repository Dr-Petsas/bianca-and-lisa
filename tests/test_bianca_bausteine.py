"""Biancas Bausteine offline: Buchstabieren, Telefonnummer, Sammler, Slot-Wahl.

Läuft ohne Netz: Kartei-/Slot-Suche wird gestummt, der Mandant kommt aus
tenants/meddent.json (lokale Datei).
"""

from bianca import buchstaben, flow, gehirn, telefon
from kern.tenants import laden


def _sit() -> dict:
    return {"tenant": laden("meddent"), "messages": [{"role": "system", "content": "x"}]}


# --- Buchstabieren --------------------------------------------------------

def test_buchstabieren_anfangsalphabet():
    d = buchstaben.deute("M wie Martha, Ü wie Übermut, L wie Ludwig, L wie Ludwig, E wie Emil, R wie Richard")
    assert d and d["name"] == "Müller"


def test_buchstabieren_striche():
    d = buchstaben.deute("B-E-R-G-E-R")
    assert d and d["name"] == "Berger"


def test_vorlesen_hat_ansagen():
    text = buchstaben.vorlesen("Öz")
    assert "wie" in text


# --- Telefonnummer --------------------------------------------------------

def test_nummer_aus_zahlwoertern():
    n = telefon.aus_satz("null eins sieben sieben sechs null null vier sechs null null")
    assert n == "01776004600"


def test_nummer_gemischt_mit_doppel():
    n = telefon.aus_satz("Die Nummer ist 0163 doppel fünf 21 98 7")
    assert n == "01635521987"


def test_sprechbar_gruppen():
    assert telefon.sprechbar("0177") .count("null") == 1


# --- Sammler: ein Satz füllt viele Felder ---------------------------------

def test_ein_satz_fuellt_viele_felder():
    sit = _sit()
    neu = gehirn.einsammeln(
        sit,
        "Guten Tag, hier ist Martin Berger, ich hätte gern nächste Woche vormittags einen Termin zur Kontrolle",
    )
    s = gehirn.sammler(sit)
    assert s["modus"] == "buchen"
    assert s["vorname"] == "Martin" and s["nachname"] == "Berger"
    assert s["grund"] and "ontroll" in s["grund"]
    assert s["wunsch"] and s["wunsch"]["minDaysAhead"] == 7 and s["wunsch"]["hourMin"] == 7
    assert {"modus", "name", "grund", "wunsch"} <= neu


def test_erste_frage_ist_schonmal():
    sit = _sit()
    gehirn.einsammeln(sit, "Ich hätte gern einen Termin")
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "schonmal"
    assert "schon" in frage.lower()


def test_arzt_genannt_und_weiss_nicht():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["warSchonMal"] = True
    s["frage"] = "arzt"
    gehirn.einsammeln(sit, "Ich war bei Doktor Patrikis")
    assert (s["arzt"] or {}).get("typ") == "genannt"
    assert "Patrikis" in (s["arzt"] or {}).get("calendarName", "")

    sit2 = _sit()
    s2 = gehirn.sammler(sit2)
    s2["modus"] = "buchen"
    s2["warSchonMal"] = True
    s2["frage"] = "arzt"
    gehirn.einsammeln(sit2, "Das weiß ich ehrlich gesagt nicht mehr")
    assert (s2["arzt"] or {}).get("typ") == "unbekannt"


def test_egal_nimmt_global():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["warSchonMal"] = True
    s["frage"] = "arzt"
    gehirn.einsammeln(sit, "Ist mir egal, Hauptsache schnell")
    assert (s["arzt"] or {}).get("typ") == "egal"


def test_nummer_steht_in_der_akte():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True, "arzt": {"typ": "genannt", "calendarId": "x", "calendarName": "Dr. Petsas"},
              "vorname": "Martin", "nachname": "Berger", "buchstabiert": True,
              "grund": "Kontrolluntersuchung", "wunsch": {}, "frage": "telefon"})
    neu = gehirn.einsammeln(sit, "Und meine Nummer haben Sie ja in der Akte.")
    assert "telefonAkte" in neu and s["telefonAkte"]
    fid, _ = gehirn.naechste_frage(sit)
    assert fid == ""  # nicht weiter auf der Nummer beharren


def test_keine_frage_schleife():
    """Live 27.08.2026: 'Und unter welcher Handynummer…' kam dreimal wortgleich.
    Bringt ein Satz nichts Neues und dieselbe Frage ist offen -> LLM (None)."""
    echt_anstossen = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        s = gehirn.sammler(sit)
        s.update({"modus": "buchen", "warSchonMal": True, "arzt": {"typ": "genannt", "calendarId": "x", "calendarName": "Dr. Petsas"},
                  "vorname": "Martin", "nachname": "Berger", "buchstabiert": True,
                  "grund": "Kontrolluntersuchung", "wunsch": {}, "frage": "telefon"})
        z = flow.zug(sit, "Ja, das passt so.")
        assert z is None
    finally:
        flow.hintergrund.anstossen = echt_anstossen


def test_telefon_wird_rueckbestaetigt():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    gehirn.einsammeln(sit, "0177 600 46 00")
    assert s["telefonOffen"] == "01776004600" and not s["telefonOk"]
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "telefon_check"
    s["frage"] = fid
    gehirn.einsammeln(sit, "Ja, genau")
    assert s["telefon"] == "01776004600" and s["telefonOk"]


# --- Slot-Wahl ------------------------------------------------------------

ANGEBOT = [
    {"iso": "2026-08-31T09:15", "spoken": "am Montag um neun Uhr fünfzehn"},
    {"iso": "2026-09-01T14:30", "spoken": "am Dienstag um vierzehn Uhr dreißig"},
    {"iso": "2026-09-02T11:00", "spoken": "am Mittwoch um elf Uhr"},
]


def test_slot_wahl_uhrzeit_ziffern():
    assert flow._slot_wahl("dann nehme ich 9 Uhr 15", ANGEBOT) == "2026-08-31T09:15"


def test_slot_wahl_uhrzeit_worte():
    assert flow._slot_wahl("neun uhr fünfzehn bitte", ANGEBOT) == "2026-08-31T09:15"


def test_slot_wahl_wochentag():
    assert flow._slot_wahl("der Dienstag passt mir gut", ANGEBOT) == "2026-09-01T14:30"


def test_slot_wahl_ordinal():
    assert flow._slot_wahl("den ersten bitte", ANGEBOT) == "2026-08-31T09:15"
    assert flow._slot_wahl("den letzten", ANGEBOT) == "2026-09-02T11:00"


def test_slot_wahl_nachmittag():
    assert flow._slot_wahl("lieber nachmittags", ANGEBOT) == "2026-09-01T14:30"


def test_slot_wahl_unklar_gibt_nichts():
    assert flow._slot_wahl("hm, schwierig", ANGEBOT) == ""


def test_naechste_woche_ab_mitternacht():
    """'Nächste Woche' zählt ab Mitternacht des Zieltags — Zeiten am Zieltag
    VOR der aktuellen Uhrzeit dürfen nicht wegfallen (live 27.08.2026)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from kern.slots import pick_slots
    now_ms = int(datetime(2026, 8, 27, 10, 41, tzinfo=ZoneInfo("Europe/Berlin")).timestamp() * 1000)
    res = pick_slots(
        ["2026-09-03T09:55:00+02:00", "2026-09-03T10:55:00+02:00"],
        wish={"minDaysAhead": 7, "hourMin": 7, "hourMax": 12},
        now_ms=now_ms,
    )
    assert res["wishMatched"]
    assert res["slots"][0]["iso"].startswith("2026-09-03T09:55")


# --- Fluss ohne Netz ------------------------------------------------------

def test_fluss_fragenkette_bis_angebot():
    echt_anstossen = flow.hintergrund.anstossen
    echt_find = flow.kal.find_slots
    flow.hintergrund.anstossen = lambda sit: None
    flow.kal.find_slots = lambda *a, **k: {
        "ok": True,
        "slots": ["2026-08-31T09:15", "2026-09-01T14:30", "2026-09-02T11:00"],
        "doctorName": "Dr. Nikolaou",
    }
    try:
        sit = _sit()
        z1 = flow.zug(sit, "Guten Tag, ich hätte gerne einen Termin.")
        assert z1 and "schon" in z1["text"].lower()

        z2 = flow.zug(sit, "Ja, ich war schon mal bei Ihnen.")
        assert z2 and "behandler" in z2["text"].lower()

        z3 = flow.zug(sit, "Bei Doktor Petsas.")
        assert z3 and "name" in z3["text"].lower()

        z4 = flow.zug(sit, "Martin Berger.")
        assert z4 and "worum" in z4["text"].lower()

        z5 = flow.zug(sit, "Eine Kontrolle bitte.")
        assert z5 and "wann" in z5["text"].lower()

        z6 = flow.zug(sit, "Nächste Woche vormittags.")
        assert z6 and "buchstabieren" in z6["text"].lower()

        z7 = flow.zug(sit, "B wie Berta, E wie Emil, R wie Richard, G wie Gustav, E wie Emil, R wie Richard.")
        assert z7 and "handynummer" in z7["text"].lower()

        z8 = flow.zug(sit, "0177 600 46 00")
        assert z8 and "wiederhole" in z8["text"].lower()

        z9 = flow.zug(sit, "Ja, stimmt.")
        assert z9 and "frei" in z9["text"].lower().replace("wäre", "wäre")
        assert sit.get("offered")

        z10 = flow.zug(sit, "Der erste bitte.")
        assert z10 and "halte ich fest" in z10["text"].lower()
        s = gehirn.sammler(sit)
        assert s["phase"] == "bestaetigen" and s["slotIso"]
    finally:
        flow.hintergrund.anstossen = echt_anstossen
        flow.kal.find_slots = echt_find


def test_buchung_bindet_angebots_kalender():
    """Vorfall 27.08.2026: Angebot kam global (Patrikis), die späte Kartei-
    Recherche stellte den Sammler auf Petsas um — gebucht wurde der Slot dann
    im falschen Kalender. Die Buchung MUSS am Angebots-Kalender kleben."""
    echt_anstossen = flow.hintergrund.anstossen
    echt_find = flow.kal.find_slots
    flow.hintergrund.anstossen = lambda sit: None
    flow.kal.find_slots = lambda *a, **k: {
        "ok": True,
        "slots": ["2026-09-08T09:00", "2026-09-08T09:15", "2026-09-08T09:30"],
        "doctorName": "Doktor Theodosios Patrikis, M.Sc.",
    }
    try:
        sit = _sit()
        s = gehirn.sammler(sit)
        s.update({
            "modus": "buchen", "warSchonMal": True,
            "arzt": {"typ": "unbekannt"},
            "vorname": "Martin", "nachname": "Berger", "buchstabiert": True,
            "grund": "Kontrolluntersuchung",
            "telefon": "01776004600", "telefonOk": True,
        })
        z = flow._angebot(sit)
        assert sit.get("offered")
        bind = sit.get("angebotKalender") or {}
        assert bind.get("calendarId") == "RHYdoQFD7oAhqIepLzC2", bind
        assert "M.Sc" not in (z["text"] or "")

        # Späte Kartei-Recherche stellt den Sammler um — darf die Buchung
        # nicht mehr umlenken:
        s["arzt"] = {"typ": "letzter", "calendarId": "zex5bmv5jfIHWVW6zHbg", "calendarName": "Dr. Petsas"}
        ctx = flow._ctx_bauen(sit)
        assert ctx["calendarId"] == "RHYdoQFD7oAhqIepLzC2", ctx
    finally:
        flow.hintergrund.anstossen = echt_anstossen
        flow.kal.find_slots = echt_find


def test_fluss_gibt_bei_fremdfrage_ab():
    echt_anstossen = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        z = flow.zug(sit, "Wie sind denn Ihre Öffnungszeiten?")
        assert z is None
    finally:
        flow.hintergrund.anstossen = echt_anstossen


def test_status_zeile_traegt_stand():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["nachname"] = "Berger"
    s["frage"] = "grund"
    zeile = gehirn.sammler(sit) and flow.status_zeile(sit)
    assert "Berger" in zeile and "grund" in zeile
