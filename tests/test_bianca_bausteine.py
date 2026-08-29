"""Biancas Bausteine offline: Buchstabieren, Telefonnummer, Sammler, Slot-Wahl.

Läuft ohne Netz: Kartei-/Slot-Suche wird gestummt, der Mandant kommt aus
tenants/meddent.json (lokale Datei).
"""

import re

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


ANGEBOT_ZWEI_MONTAGE = [
    {"iso": "2026-08-31T10:00", "spoken": "am Montag um zehn Uhr"},
    {"iso": "2026-08-31T12:30", "spoken": "am Montag um zwölf Uhr dreißig"},
    {"iso": "2026-09-01T09:15", "spoken": "am Dienstag um neun Uhr fünfzehn"},
]


def test_slot_wahl_um_zahlwort_ohne_uhr_live_2352():
    """Live 28.08.2026, 23:52: 'Montag um zehn, bitte.' fiel durch — der Satz
    wurde als neuer Wunsch geerntet, das Angebot kam wortgleich wieder und der
    Wiederholungs-Waechter liess nur noch 'Gut.' uebrig. Keine Buchung."""
    assert flow._slot_wahl("Montag um zehn, bitte.", ANGEBOT_ZWEI_MONTAGE) == "2026-08-31T10:00"
    assert flow._slot_wahl("Ja, Montag um zehn.", ANGEBOT_ZWEI_MONTAGE) == "2026-08-31T10:00"


def test_slot_wahl_wochentag_plus_stunde_grenzen_gemeinsam_ein():
    # Wochentag allein waere doppeldeutig (zwei Montage), die Stunde allein
    # eindeutig — und umgekehrt: zwei Zehn-Uhr-Slots braucht der Wochentag.
    assert flow._slot_wahl("Montag um halb eins", ANGEBOT_ZWEI_MONTAGE) == "2026-08-31T12:30"
    zwei_tage_zehn = [
        {"iso": "2026-08-31T10:00", "spoken": "am Montag um zehn Uhr"},
        {"iso": "2026-09-01T10:00", "spoken": "am Dienstag um zehn Uhr"},
    ]
    assert flow._slot_wahl("dann Montag um zehn", zwei_tage_zehn) == "2026-08-31T10:00"
    assert flow._slot_wahl("lieber Dienstag um zehn Uhr", zwei_tage_zehn) == "2026-09-01T10:00"


def test_slot_wahl_wochentag_allein_bleibt_doppeldeutig():
    assert flow._slot_wahl("dann am Montag", ANGEBOT_ZWEI_MONTAGE) == ""


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


# --- Termin-Verwaltung: ansagen, absagen, verschieben ----------------------

from bianca import verwalten  # noqa: E402


GEFUNDEN = {
    "ok": True,
    "patient": {"id": "pat-1", "firstName": "Martin", "lastName": "Berger"},
    "appointments": [{
        "id": "apt-1", "iso": "2026-09-03T10:00", "date": "2026-09-03",
        "calendarId": "zex5bmv5jfIHWVW6zHbg", "doctorName": "Dr. Petsas",
        "motivId": "vm-1", "motivName": "01 Kontrolluntersuchung",
        "spoken": "am Donnerstag, den dritten September um zehn Uhr bei Dr. Petsas",
    }],
}


def test_modus_erkennung_verwaltung():
    sit = _sit()
    gehirn.einsammeln(sit, "Ich möchte meinen Termin absagen.")
    assert gehirn.sammler(sit)["modus"] == "absagen"

    sit2 = _sit()
    gehirn.einsammeln(sit2, "Können wir meinen Termin verschieben?")
    assert gehirn.sammler(sit2)["modus"] == "verschieben"

    sit3 = _sit()
    gehirn.einsammeln(sit3, "Wann ist mein Termin nochmal?")
    assert gehirn.sammler(sit3)["modus"] == "auskunft"

    # "sagen, ab wann" ist eine Auskunftsfrage, KEIN Storno.
    sit4 = _sit()
    gehirn.einsammeln(sit4, "Können Sie mir sagen, ab wann Sie morgens aufhaben?")
    assert gehirn.sammler(sit4)["modus"] != "absagen"


def test_absage_im_angebot_bleibt_buchung():
    """'Absagen'/'verschieben' waehrend ein Buchungs-Angebot offen ist, meint
    das Angebot — der Modus darf nicht in die Bestandsverwaltung kippen."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "phase": "angebot"})
    gehirn.einsammeln(sit, "Nee, das passt nicht — dann sagen Sie es ab.")
    assert s["modus"] == "buchen"


def test_absage_fluss_komplett():
    echt_find = verwalten.kal.find_patient_appointments
    echt_cancel = verwalten.kal.cancel_by_id
    echt_anstossen = verwalten.hintergrund.anstossen
    aufrufe = {}
    verwalten.kal.find_patient_appointments = lambda t, c: dict(GEFUNDEN)
    def _cancel(t, c, aid):
        aufrufe["aid"] = aid
        return {"ok": True, "cancelled": True, "appointmentId": aid, "spoken": "Der Termin ist abgesagt."}
    verwalten.kal.cancel_by_id = _cancel
    verwalten.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        z1 = flow.zug(sit, "Guten Tag, ich muss leider meinen Termin absagen.")
        assert z1 and "name" in z1["text"].lower()

        z2 = flow.zug(sit, "Martin Berger.")
        assert z2 and "wirklich absagen" in z2["text"].lower()
        assert gehirn.sammler(sit)["phase"] == "absage_bestaetigen"

        z3 = flow.zug(sit, "Ja, bitte.")
        assert z3 and "abgesagt" in z3["text"].lower()
        assert aufrufe["aid"] == "apt-1"
        assert "neuen termin" in z3["text"].lower()

        z4 = flow.zug(sit, "Nein, danke.")
        assert z4 and "sonst noch" in z4["text"].lower()
    finally:
        verwalten.kal.find_patient_appointments = echt_find
        verwalten.kal.cancel_by_id = echt_cancel
        verwalten.hintergrund.anstossen = echt_anstossen


def test_absage_dann_neubuchung():
    echt_find = verwalten.kal.find_patient_appointments
    echt_cancel = verwalten.kal.cancel_by_id
    echt_anstossen = verwalten.hintergrund.anstossen
    verwalten.kal.find_patient_appointments = lambda t, c: dict(GEFUNDEN)
    verwalten.kal.cancel_by_id = lambda t, c, aid: {"ok": True, "cancelled": True, "appointmentId": aid, "spoken": "Der Termin ist abgesagt."}
    verwalten.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        flow.zug(sit, "Ich möchte meinen Termin absagen.")
        flow.zug(sit, "Martin Berger.")
        flow.zug(sit, "Ja.")
        z = flow.zug(sit, "Ja, gerne einen neuen.")
        s = gehirn.sammler(sit)
        assert s["modus"] == "buchen"
        assert z and _s_frage(z)
        # Behandler des abgesagten Termins ist als Vorgabe uebernommen:
        assert (s["arzt"] or {}).get("calendarId") == "zex5bmv5jfIHWVW6zHbg"
    finally:
        verwalten.kal.find_patient_appointments = echt_find
        verwalten.kal.cancel_by_id = echt_cancel
        verwalten.hintergrund.anstossen = echt_anstossen


def _s_frage(z: dict) -> str:
    return (z or {}).get("text") or ""


def test_auskunft_und_folgeabsage():
    echt_find = verwalten.kal.find_patient_appointments
    verwalten.kal.find_patient_appointments = lambda t, c: dict(GEFUNDEN)
    try:
        sit = _sit()
        z1 = flow.zug(sit, "Wann ist mein Termin nochmal?")
        assert z1 and "name" in z1["text"].lower()

        z2 = flow.zug(sit, "Martin Berger.")
        assert z2 and "nächster termin" in z2["text"].lower()
        assert "Petsas" in z2["text"]

        z3 = flow.zug(sit, "Ach, den können Sie absagen bitte.")
        assert z3 and "wirklich absagen" in z3["text"].lower()
        assert gehirn.sammler(sit)["modus"] == "absagen"
    finally:
        verwalten.kal.find_patient_appointments = echt_find


def test_verschieben_fluss_komplett():
    echt_find = verwalten.kal.find_patient_appointments
    echt_slots = verwalten.kal.find_slots
    echt_move = verwalten.kal.move_appointment
    aufrufe = {}
    verwalten.kal.find_patient_appointments = lambda t, c: dict(GEFUNDEN)
    verwalten.kal.find_slots = lambda t, c, **k: {
        "ok": True,
        "slots": ["2026-09-03T10:00", "2026-09-08T14:30", "2026-09-09T15:00"],
        "doctorName": "Dr. Petsas",
    }
    def _move(t, ctx, **k):
        aufrufe["aid"] = ctx.get("appointmentId")
        aufrufe["iso"] = k.get("slot_iso")
        return {"ok": True, "moved": True, "appointmentId": ctx.get("appointmentId"),
                "slotIso": k.get("slot_iso"), "spoken": "Der Termin liegt jetzt am Dienstag."}
    verwalten.kal.move_appointment = _move
    try:
        sit = _sit()
        z1 = flow.zug(sit, "Ich würde meinen Termin gern verschieben.")
        assert z1 and "name" in z1["text"].lower()

        z2 = flow.zug(sit, "Martin Berger.")
        assert z2 and "besser" in z2["text"].lower()
        assert gehirn.sammler(sit)["phase"] == "verschieb_wunsch"

        z3 = flow.zug(sit, "Lieber nachmittags.")
        assert z3 and sit.get("offered"), z3
        # Der eigene Bestandstermin (10:00) darf NICHT angeboten werden:
        assert all(not o["iso"].startswith("2026-09-03T10:00") for o in sit["offered"])

        z4 = flow.zug(sit, "Der erste bitte.")
        assert z4 and "passt das so" in z4["text"].lower()

        z5 = flow.zug(sit, "Ja.")
        assert z5 and "sonst noch" in z5["text"].lower()
        assert aufrufe["aid"] == "apt-1"
        assert aufrufe["iso"] and aufrufe["iso"] != "2026-09-03T10:00"
    finally:
        verwalten.kal.find_patient_appointments = echt_find
        verwalten.kal.find_slots = echt_slots
        verwalten.kal.move_appointment = echt_move


def test_verwaltung_kein_termin_gefunden():
    echt_find = verwalten.kal.find_patient_appointments
    verwalten.kal.find_patient_appointments = lambda t, c: {"ok": True, "patient": {}, "appointments": []}
    try:
        sit = _sit()
        flow.zug(sit, "Ich möchte meinen Termin absagen.")
        z = flow.zug(sit, "Martin Berger.")
        assert z and "keinen kommenden termin" in z["text"].lower()
        assert "neuen termin" in z["text"].lower()
    finally:
        verwalten.kal.find_patient_appointments = echt_find


def test_verwaltung_status_zeile():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "absagen", "nachname": "Berger", "frage": "absage_ok", "phase": "absage_bestaetigen"})
    zeile = flow.status_zeile(sit)
    assert "absagen" in zeile and "Berger" in zeile


# --- Live-Vorfaelle 27.08.2026 (nachmittags): Schleifen, Hoerfehler, Glitches


def test_arzt_hoerfehler_petzers():
    """STT hoerte 'Dr. Petzers' statt 'Dr. Petsas' — muss trotzdem matchen."""
    from bianca import arzt as arztmod
    tenant = laden("meddent")
    d = arztmod.deute("Ich hätte gerne einen Termin bei Dr. Petzers morgen.", tenant)
    assert d and d["typ"] == "genannt" and "Petsas" in d["calendarName"]


def test_arzt_kein_treffer_bei_vornamen():
    """'Peter' (Patienten-Vorname, kein Arzt-Kontext) darf NICHT auf Petsas springen."""
    from bianca import arzt as arztmod
    tenant = laden("meddent")
    d = arztmod.deute("Mein Name ist Peter Müller.", tenant)
    assert not (d and d.get("typ") == "genannt")


def test_aeh_nein_ist_nein():
    """'Äh, nein.' wurde live NICHT als Nein erkannt -> Zustands-Desync."""
    assert gehirn.ist_nein("Äh, nein.")
    assert gehirn.ist_ja("Also ja, gerne.")
    assert gehirn.ist_nein("Hm, nee.")
    assert not gehirn.ist_ja("Ähm, nein danke.")


def test_bin_neu_ist_kein_name():
    """'Ich bin neu bei Ihnen' wurde live als Name geerntet ('Danke, Neu
    Ihnen') — Neupatient-Floskeln duerfen NIE in die Namensfelder, zaehlen
    aber als Schonmal-Nein."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "name"})
    neu = gehirn.einsammeln(sit, "Ich bin neu bei Ihnen")
    assert not s["vorname"] and not s["nachname"]
    assert "name" not in neu and "nachname" not in neu
    assert s["warSchonMal"] is False


def test_neupatient_floskeln_kein_name():
    """Auch 'ganz neu', 'noch nie', 'zum ersten Mal' ergeben keinen Namen."""
    for satz in ["Ich bin ganz neu bei euch", "Ich war noch nie da", "Bin zum ersten Mal hier"]:
        sit = _sit()
        s = gehirn.sammler(sit)
        s.update({"modus": "buchen", "frage": "name"})
        gehirn.einsammeln(sit, satz)
        assert not s["vorname"] and not s["nachname"], satz
        assert s["warSchonMal"] is False, satz


def test_ich_bin_paul_neumann_bleibt_name():
    """Gegenprobe: 'bin NEUmann' ist KEIN 'bin neu' — echter Name bleibt."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "name"})
    gehirn.einsammeln(sit, "Ich bin Paul Neumann")
    assert s["vorname"] == "Paul" and s["nachname"] == "Neumann"
    assert s["warSchonMal"] is None  # kein falsches Neupatient-Signal


def test_nachname_neu_funktioniert():
    """Gegenprobe: der echte Nachname 'Neu' wird weiter aufgenommen."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "name"})
    gehirn.einsammeln(sit, "Mein Name ist Anna Neu")
    assert s["vorname"] == "Anna" and s["nachname"] == "Neu"


def test_auch_paul_wird_paul():
    """'Auch Paul' auf die Vornamens-Frage ergab Vorname 'Auch' (live)."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True, "nachname": "Hacke", "frage": "vorname"})
    gehirn.einsammeln(sit, "Auch Paul")
    assert s["vorname"] == "Paul"


def test_englische_ziffern():
    """Web-Speech rutschte ins Englische: 'six hundred' = 600 (live)."""
    assert telefon.ziffern("Null eins sieben sieben six hundred vier six hundred") == "01776004600"
    assert telefon.aus_satz("null eins sieben sieben sechshundert vier sechshundert") == "01776004600"


def test_telefon_stueckweise_diktiert():
    """Nummer in Etappen: Fragmente sammeln, bis die Kette plausibel ist."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True, "arzt": {"typ": "genannt", "calendarId": "x", "calendarName": "Dr. Petsas"},
              "vorname": "Martin", "nachname": "Berger", "buchstabiert": True,
              "grund": "Kontrolluntersuchung", "wunsch": {}, "frage": "telefon"})
    gehirn.einsammeln(sit, "null eins sieben sieben")
    assert s["telefonTeil"] == "0177" and not s["telefonOffen"]
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "telefon" and "fehlt" in frage.lower()
    gehirn.einsammeln(sit, "sechs null null vier sechs null null")
    assert s["telefonOffen"] == "01776004600" and not s["telefonTeil"]
    fid2, _ = gehirn.naechste_frage(sit)
    assert fid2 == "telefon_check"


def test_frage_eskalation_statt_schleife():
    """Zweimal nichts Verwertbares auf dieselbe Pflichtfrage: Standard setzen
    und weitergehen — die Live-Schleife ('Handynummer?' im Kreis) ist tabu."""
    echt_anstossen = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        s = gehirn.sammler(sit)
        s.update({"modus": "buchen", "warSchonMal": True, "frage": "arzt"})
        z1 = flow.zug(sit, "Das müssen Sie doch wissen.")
        assert z1 is None  # erster Leerlauf -> LLM darf kurz antworten
        z2 = flow.zug(sit, "Das weißt du doch alles.")
        assert z2 is not None  # zweiter Leerlauf -> Eskalation, KEIN None mehr
        assert (s["arzt"] or {}).get("typ") == "egal"
        assert s["frage"] != "arzt"
    finally:
        flow.hintergrund.anstossen = echt_anstossen


def test_angebots_wache_faengt_fantasie_termine():
    """LLM erfand 'Mittwoch, den 24. Juli, um 09:30 Uhr' ohne echte Slots —
    die Wache ersetzt das durch die offene Sammler-Frage."""
    from bianca import agent as agentmod
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True, "frage": "arzt"})
    text = "Ich biete Ihnen einen Termin am Mittwoch, den 24. Juli, um 09:30 Uhr an. Passt Ihnen diese Uhrzeit?"
    raus = agentmod._nachbessern(sit, text)
    assert "24. Juli" not in raus and "09:30" not in raus
    assert "behandler" in raus.lower() or "arzt" in raus.lower()


def test_frage_anker_haengt_offene_frage_an():
    """Antwortet das LLM am Thema vorbei, wird die offene Frage angehängt,
    fremde Schlussfragen ('Möchten Sie buchen?') fliegen raus."""
    from bianca import agent as agentmod
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True, "arzt": {"typ": "genannt", "calendarId": "x", "calendarName": "Dr. Petsas"},
              "vorname": "Paul", "nachname": "Hacke", "bekannt": True, "buchstabiert": True,
              "grund": "Kontrolluntersuchung", "wunsch": {}, "frage": "telefon"})
    text = "Alles klar, ich habe Ihre Daten notiert. Möchten Sie einen Termin buchen?"
    raus = agentmod._nachbessern(sit, text)
    assert "handynummer" in raus.lower()
    assert "möchten sie einen termin buchen" not in raus.lower()


def test_absage_trennverb_mit_doch_wieder():
    """'Sagen Sie den Termin doch wieder ab' muss den Absage-Modus setzen —
    live 27.08. fiel der Satz durch und das LLM übernahm."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "phase": "gebucht"})
    gehirn.einsammeln(sit, "Ach warten Sie — bitte sagen Sie den Termin doch wieder ab.")
    assert s["modus"] == "absagen"


def test_terminwahl_gibt_nie_ans_llm_ab():
    """Unklare Antwort ('Ja.') bei mehreren Bestandsterminen: deterministische
    Rückfrage statt None — sonst erfindet das LLM eine Absage."""
    from bianca import verwalten
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "absagen", "phase": "wahl", "frage": "terminwahl",
              "vorname": "Michael", "nachname": "Peters"})
    sit["gefunden"] = [
        {"id": "a1", "iso": "2026-08-28T10:30:00+02:00", "spoken": "morgen um zehn Uhr dreißig bei Dr. Petsas"},
        {"id": "a2", "iso": "2026-08-28T10:45:00+02:00", "spoken": "morgen um zehn Uhr fünfundvierzig bei Dr. Petsas"},
    ]
    z = verwalten.zug(sit, "Ja.", set())
    assert z is not None and "ersten" in (z.get("text") or "").lower()
    z2 = verwalten.zug(sit, "Den ersten bitte.", set())
    assert z2 is not None and "wirklich absagen" in (z2.get("text") or "").lower()


def test_zwischenfrage_erkennung():
    """Fragen des Anrufers werden als Abschweifung erkannt — Verweigerungen
    und Meta-Kommentare nicht (die dürfen weiter eskalieren)."""
    for satz in ["Was kostet denn eine Kontrolle?", "Wo kann ich bei Ihnen parken",
                 "Muss ich nüchtern kommen", "Äh, wie lange dauert das denn",
                 "Haben Sie einen Aufzug?", "Und wieviel kostet das"]:
        assert gehirn.ist_zwischenfrage(satz), satz
    for satz in ["Das müssen Sie doch wissen.", "Das weißt du doch alles.",
                 "Hm.", "Na gut, von mir aus.", "Ich sag dazu nichts."]:
        assert not gehirn.ist_zwischenfrage(satz), satz


def test_abschweifung_zaehlt_nicht_als_leerlauf():
    """Zwei Zwischenfragen hintereinander: beide gehen ans LLM, KEINE
    Eskalation — erst echte Nicht-Antworten schalten weiter (Chef 27.08.:
    'Abschweifungen müssen erlaubt sein')."""
    echt_anstossen = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        s = gehirn.sammler(sit)
        s.update({"modus": "buchen", "warSchonMal": True, "frage": "arzt"})
        assert flow.zug(sit, "Was kostet denn so eine Kontrolle?") is None
        assert flow.zug(sit, "Und wo kann ich bei Ihnen parken?") is None
        assert not (sit.get("frageLeer") or {})  # Abschweifungen zählen nicht
        assert s["frage"] == "arzt" and s["arzt"] is None  # offene Frage bleibt
        assert flow.zug(sit, "Das müssen Sie doch wissen.") is None  # 1. Leerlauf
        z = flow.zug(sit, "Sag ich nicht.")  # 2. Leerlauf -> Eskalation
        assert z is not None and (s["arzt"] or {}).get("typ") == "egal"
    finally:
        flow.hintergrund.anstossen = echt_anstossen


def test_kurz_zustimmung_stark_super():
    """'Stark.' / 'Super!' als ganze Äußerung ist ein Ja — 'Gut, aber ...'
    nicht (das ist eine Rückfrage und bleibt beim LLM)."""
    for satz in ["Stark.", "Super!", "Perfekt", "Äh, sehr gut.", "In Ordnung."]:
        assert gehirn.ist_ja(satz), satz
    assert not gehirn.ist_ja("Gut, aber was kostet das?")
    assert gehirn.ist_zwischenfrage("Gut, aber was kostet das?")


def test_terminwahl_abschweifung_geht_ans_llm():
    """Zwischenfrage während der Terminwahl: LLM darf antworten (None),
    eine klare Wahl danach läuft deterministisch weiter."""
    from bianca import verwalten
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "absagen", "phase": "wahl", "frage": "terminwahl",
              "vorname": "Michael", "nachname": "Peters"})
    sit["gefunden"] = [
        {"id": "a1", "iso": "2026-08-28T10:30:00+02:00", "spoken": "morgen um zehn Uhr dreißig"},
        {"id": "a2", "iso": "2026-08-28T10:45:00+02:00", "spoken": "morgen um zehn Uhr fünfundvierzig"},
    ]
    assert verwalten.zug(sit, "Warum wollen Sie das denn wissen?", set()) is None
    z = verwalten.zug(sit, "Den zweiten bitte.", set())
    assert z is not None and "wirklich absagen" in (z.get("text") or "").lower()


def test_erledigt_wache_blockt_falsche_absage_behauptung():
    """LLM behauptet 'ich sage den Termin ab', obwohl kein Werkzeug lief:
    Wache ersetzt das durch die letzte offene Fluss-Frage (live 27.08.:
    beide Termine standen noch im Kalender)."""
    from bianca import agent as agentmod
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "absagen", "phase": "wahl", "frage": "terminwahl"})
    sit["flussFrage"] = "Welchen möchten Sie absagen?"
    text = "Alles klar, ich sage den Termin morgen um zehn Uhr dreißig bei Doktor Petsas für Sie ab."
    raus = agentmod._nachbessern(sit, text, werkzeug_lief=False)
    assert "sage" not in raus.lower() or "welchen" in raus.lower()
    assert "Welchen möchten Sie absagen?" in raus
    # Lief das Werkzeug wirklich, bleibt der Text unangetastet.
    gleich = agentmod._nachbessern(sit, text, werkzeug_lief=True)
    assert gleich == text


def test_noch_nicht_ist_nein():
    """'Äh, noch nicht' auf 'Waren Sie schon mal bei uns?' ist ein Nein —
    live 27.08. 14:53 fiel es durch und die Frage kam doppelt."""
    for satz in ["Äh, noch nicht", "Noch nicht.", "Noch nie", "Bisher nicht"]:
        assert gehirn.ist_nein(satz), satz
    # Nur als GANZE Äußerung — mitten im Satz bleibt es neutral.
    assert not gehirn.ist_nein("Das passt noch nicht ganz, lieber später")
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "schonmal"})
    gehirn.einsammeln(sit, "Äh, noch nicht")
    assert s["warSchonMal"] is False


def test_jap_und_jep_sind_ja():
    """'Jap, bitte' scheiterte live am Wortgrenzen-Raster — das LLM übernahm
    und buchte selbst (Doppelbuchung). Jetzt deterministisch."""
    for satz in ["Jap, bitte", "Jep.", "Jo, passt", "Jawoll"]:
        assert gehirn.ist_ja(satz), satz
    assert not gehirn.ist_ja("Japan ist schön")


def test_buchen_neue_nummer_weicht_von_akte_ab_keine_sms_zusage():
    """Live 29.08.2026 02:19: Bestandsakte trug 0123456789, der Anrufer
    bestaetigte 0177 6004600 — Bianca versprach 'SMS kommt gleich', die
    Plattform schickte aber an die Akten-Nummer (ins Leere). Jetzt: Notiz
    an den Termin + ehrliche Ansage, kein SMS-Versprechen."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "phase": "bestaetigen", "frage": "bestaetigung",
        "vorname": "Peter", "nachname": "Müller", "patientId": "Uz5O",
        "telefon": "01776004600", "aktePhone": "0123456789",
        "slotIso": "2026-09-01T09:15",
    })
    echt_book, echt_note = flow.kal.book_slot, flow.kal.note_appointment
    notizen: list[str] = []

    def _note(tenant, ctx, sit=None, *, note=""):
        notizen.append(note)
        return {"ok": True, "noted": True}

    flow.kal.book_slot = lambda tenant, ctx, slot_iso="": {
        "ok": True, "booked": True, "slotIso": slot_iso or "2026-09-01T09:15",
        "appointmentId": "e7ho", "spoken": "Der Termin ist fest eingetragen.",
    }
    flow.kal.note_appointment = _note
    try:
        res = flow._buchen(sit)
    finally:
        flow.kal.book_slot, flow.kal.note_appointment = echt_book, echt_note
    assert "SMS" not in res["text"]
    assert "neue Handynummer" in res["text"]
    assert notizen and "01776004600" in notizen[0] and "0123456789" in notizen[0]


def test_buchen_gleiche_nummer_wie_akte_verspricht_sms():
    """Gleiche Nummer (nur anderes Format) ist KEIN Konflikt — die
    SMS-Zusage bleibt, es wird keine Notiz geschrieben."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "phase": "bestaetigen", "frage": "bestaetigung",
        "vorname": "Peter", "nachname": "Müller", "patientId": "Uz5O",
        "telefon": "+49 177 6004600", "aktePhone": "01776004600",
        "slotIso": "2026-09-01T09:15",
    })
    echt_book, echt_note = flow.kal.book_slot, flow.kal.note_appointment
    notizen: list[str] = []

    def _note(tenant, ctx, sit=None, *, note=""):
        notizen.append(note)
        return {"ok": True, "noted": True}

    flow.kal.book_slot = lambda tenant, ctx, slot_iso="": {
        "ok": True, "booked": True, "slotIso": slot_iso or "2026-09-01T09:15",
        "appointmentId": "e7ho", "spoken": "Der Termin ist fest eingetragen.",
    }
    flow.kal.note_appointment = _note
    try:
        res = flow._buchen(sit)
    finally:
        flow.kal.book_slot, flow.kal.note_appointment = echt_book, echt_note
    assert "Die Bestätigung kommt gleich per SMS." in res["text"]
    assert not notizen


# --- Akten-Nummer-Konflikt: telefon_alt (Chef 29.08.2026) -------------------

def _konflikt_sit() -> dict:
    """Bestandsakte mit Alt-Nummer, Anrufer hat eine NEUE Nummer bestaetigt."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "warSchonMal": True,
        "vorname": "Peter", "nachname": "Müller", "buchstabiert": True,
        "patientId": "Uz5O", "bekannt": True, "aktePhone": "0123456789",
        "telefon": "01776004600", "telefonOk": True,
    })
    return sit


def test_telefon_alt_frage_nennt_die_alte_nummer():
    sit = _konflikt_sit()
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "telefon_alt"
    assert telefon.sprechbar("0123456789") in frage
    assert "löschen" in frage and "SMS" in frage


def test_telefon_alt_loeschen_ruft_update_und_traegt_neue_nummer_ein():
    sit = _konflikt_sit()
    s = gehirn.sammler(sit)
    s["frage"] = "telefon_alt"
    echt = flow.telefon_aktualisieren
    rufe: list[tuple[str, str]] = []

    def _update(tenant, patient_id, phone):
        rufe.append((patient_id, phone))
        return {"ok": True, "patientId": patient_id,
                "mobilePhoneNumber": "+491776004600", "previous": "0123456789"}

    flow.telefon_aktualisieren = _update
    try:
        res = flow.zug(sit, "Löschen Sie die alte bitte und nehmen Sie die neue.")
    finally:
        flow.telefon_aktualisieren = echt
    assert rufe == [("Uz5O", "01776004600")]
    assert s["telefonAlt"] == "neu"
    assert s["aktePhone"] == "01776004600"
    assert res and res["text"].startswith("Erledigt")


def test_telefon_alt_sms_an_die_alte_nummer_ohne_update():
    sit = _konflikt_sit()
    s = gehirn.sammler(sit)
    s["frage"] = "telefon_alt"
    echt = flow.telefon_aktualisieren
    flow.telefon_aktualisieren = lambda *a, **k: (_ for _ in ()).throw(AssertionError("kein Update erwartet"))
    try:
        res = flow.zug(sit, "Schicken Sie die Bestätigung ruhig an die alte Nummer.")
    finally:
        flow.telefon_aktualisieren = echt
    assert s["telefonAlt"] == "akte"
    assert s["aktePhone"] == "0123456789"
    assert res and "bleibt in der Akte" in res["text"]

    # Buchung danach: SMS-Zusage auf die AKTEN-Nummer, keine Praxis-Notiz.
    s.update({"phase": "bestaetigen", "frage": "bestaetigung", "slotIso": "2026-09-01T09:15"})
    echt_book, echt_note = flow.kal.book_slot, flow.kal.note_appointment
    notizen: list[str] = []
    flow.kal.book_slot = lambda tenant, ctx, slot_iso="": {
        "ok": True, "booked": True, "slotIso": slot_iso,
        "appointmentId": "e7ho", "spoken": "Der Termin ist fest eingetragen.",
    }
    flow.kal.note_appointment = lambda tenant, ctx, sit=None, *, note="": notizen.append(note) or {"ok": True}
    try:
        res2 = flow._buchen(sit)
    finally:
        flow.kal.book_slot, flow.kal.note_appointment = echt_book, echt_note
    assert "an die Nummer aus Ihrer Akte" in res2["text"]
    assert not notizen


def test_telefon_alt_nochmal_vorlesen_beliebig_oft():
    sit = _konflikt_sit()
    s = gehirn.sammler(sit)
    s["frage"] = "telefon_alt"
    erwartet = telefon.sprechbar("0123456789")
    for satz in ("Wie bitte, welche Nummer?", "Sagen Sie die Nummer bitte nochmal.", "Nochmal langsamer bitte."):
        res = flow.zug(sit, satz)
        assert res and erwartet in res["text"], satz
    assert s["telefonAlt"] == ""  # Entscheidung weiter offen


def test_telefon_alt_update_kaputt_faellt_auf_praxisnotiz_zurueck():
    sit = _konflikt_sit()
    s = gehirn.sammler(sit)
    s["frage"] = "telefon_alt"
    echt = flow.telefon_aktualisieren
    flow.telefon_aktualisieren = lambda *a, **k: {"ok": False, "error": "http_500"}
    try:
        res = flow.zug(sit, "Bitte löschen, die neue Nummer gilt.")
    finally:
        flow.telefon_aktualisieren = echt
    assert s["telefonAlt"] == "notiz"
    assert s["aktePhone"] == "0123456789"
    assert res and "klappt gerade technisch nicht" in res["text"]

    s.update({"phase": "bestaetigen", "frage": "bestaetigung", "slotIso": "2026-09-01T09:15"})
    echt_book, echt_note = flow.kal.book_slot, flow.kal.note_appointment
    notizen: list[str] = []
    flow.kal.book_slot = lambda tenant, ctx, slot_iso="": {
        "ok": True, "booked": True, "slotIso": slot_iso,
        "appointmentId": "e7ho", "spoken": "Der Termin ist fest eingetragen.",
    }
    flow.kal.note_appointment = lambda tenant, ctx, sit=None, *, note="": notizen.append(note) or {"ok": True}
    try:
        res2 = flow._buchen(sit)
    finally:
        flow.kal.book_slot, flow.kal.note_appointment = echt_book, echt_note
    assert notizen and "01776004600" in notizen[0]
    assert "neue Handynummer" in res2["text"]


def test_telefon_alt_eskalation_nimmt_die_neue_nummer():
    """Zweimal keine klare Wahl: die frisch bestaetigte Nummer gilt; das
    Umtragen holt _buchen als Sicherheitsnetz VOR der SMS nach."""
    sit = _konflikt_sit()
    s = gehirn.sammler(sit)
    s["frage"] = "telefon_alt"
    sit["frageLeer"] = {"telefon_alt": 1}  # erster Leerlauf ist schon verbraucht
    res = flow.zug(sit, "Sag ich nicht.")
    assert s["telefonAlt"] == "neu"
    assert res and "Ihre neue Nummer" in res["text"]

    s.update({"phase": "bestaetigen", "frage": "bestaetigung", "slotIso": "2026-09-01T09:15"})
    echt_upd = flow.telefon_aktualisieren
    echt_book, echt_note = flow.kal.book_slot, flow.kal.note_appointment
    rufe: list[str] = []
    flow.telefon_aktualisieren = lambda tenant, pid, phone: rufe.append(phone) or {"ok": True}
    flow.kal.book_slot = lambda tenant, ctx, slot_iso="": {
        "ok": True, "booked": True, "slotIso": slot_iso,
        "appointmentId": "e7ho", "spoken": "Der Termin ist fest eingetragen.",
    }
    flow.kal.note_appointment = lambda tenant, ctx, sit=None, *, note="": {"ok": True}
    try:
        res2 = flow._buchen(sit)
    finally:
        flow.telefon_aktualisieren = echt_upd
        flow.kal.book_slot, flow.kal.note_appointment = echt_book, echt_note
    assert rufe == ["01776004600"]
    assert "Die Bestätigung kommt gleich per SMS." in res2["text"]


def test_telefon_aktualisieren_trockenlauf_und_wachen():
    from kern import patients as patmod
    echt = patmod.WRITE_LIVE
    patmod.WRITE_LIVE = False
    try:
        res = patmod.telefon_aktualisieren({}, "Uz5O", "0177 600 46 00")
        assert res["ok"] and res["dryRun"]
        assert res["mobilePhoneNumber"] == "+491776004600"
        assert not patmod.telefon_aktualisieren({}, "", "01776004600")["ok"]
        assert not patmod.telefon_aktualisieren({}, "Uz5O", "123")["ok"]
    finally:
        patmod.WRITE_LIVE = echt


def test_fluss_sync_nach_llm_buchung():
    """Bucht das LLM selbst per book_slot, zieht die Zustandsmaschine nach:
    Phase 'gebucht', keine offene Frage — sonst fragt sie 'Soll ich eintragen?'
    NACH der Buchung nochmal und bucht doppelt (live 27.08. 14:53)."""
    from bianca import agent as agentmod
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "phase": "bestaetigen", "frage": "bestaetigung"})
    agentmod._fluss_sync(sit, ["book_slot"], {"booked": True, "slotIso": "2026-08-28T13:15:00+02:00"})
    assert s["phase"] == "gebucht" and s["frage"] == "" and s["slotIso"] == "2026-08-28T13:15:00+02:00"
    # Absage über das LLM: Phase fertig, gefundene Termine verworfen.
    sit2 = _sit()
    s2 = gehirn.sammler(sit2)
    s2.update({"modus": "absagen", "phase": "wahl", "frage": "terminwahl"})
    sit2["lastCancel"] = {"ok": True}
    agentmod._fluss_sync(sit2, ["cancel_appointment"], None)
    assert s2["phase"] == "fertig" and s2["frage"] == ""


def test_kartei_treffer_mit_falschem_vornamen_wird_verworfen():
    """Suche nach 'Don Johnson' findet nur 'Nikki Johnson': der Treffer wird
    verworfen statt blind übernommen (live 27.08.: Buchung auf falscher Akte,
    SMS an fremde Nummer)."""
    from kern import patients as patmod
    echt = patmod.search_patients
    patmod.search_patients = lambda tenant, q: {"ok": True, "patients": [
        {"id": "yxq123", "firstName": "Nikki", "lastName": "Johnson", "mobilePhoneNumber": "+4917673353526"},
    ]}
    try:
        tenant = laden("meddent")
        raus = patmod.patient_aufloesen(tenant, {"firstName": "Don", "lastName": "Johnson"})
        assert not raus.get("id")  # Nikki ist NICHT Don
        gleich = patmod.patient_aufloesen(tenant, {"firstName": "Nikki", "lastName": "Johnson"})
        assert gleich.get("id") == "yxq123"  # echter Treffer bleibt Treffer
        nur_nachname = patmod.patient_aufloesen(tenant, {"lastName": "Johnson"})
        assert nur_nachname.get("id") == "yxq123"  # ohne Vornamen zählt der Nachname
    finally:
        patmod.search_patients = echt


def test_arzt_sprechname_ohne_vornamen():
    """Gesprochen wird nur Titel + Nachname — englisch klingende Vornamen
    ('Michael') liest die Stimme sonst englisch (Chef 27.08.)."""
    from kern.patients import arzt_sprechname
    assert arzt_sprechname("Dr. Michael Petsas, M.Sc.") == "Doktor Petsas"
    assert arzt_sprechname("Prof. Dr. Anna Meier") == "Professor Meier"
    assert arzt_sprechname("Dr. Petsas") == "Doktor Petsas"
    assert arzt_sprechname("Patrikis") == "Patrikis"
    assert arzt_sprechname("") == ""


def test_tts_aussprache_umschrift():
    """'Michael' wird fuer den Mund zu 'Micha-el' — Logs bleiben unveraendert."""
    from kern import tts as ttsmod
    text = "Dann halte ich fest: für Michael Peters bei Doktor Petsas."
    for cre, ersatz in ttsmod._AUSSPRACHE:
        text = cre.sub(ersatz, text)
    assert "Micha-el Peters" in text and "Michael" not in text


def test_wunsch_uhrzeit_in_worten_und_statt():
    """'zwölf Uhr zwanzig' zaehlt als Uhrzeit; bei 'statt X bitte Y' zaehlt
    die ZIEL-Zeit (live 27.08.: 'statt zwölf Uhr fünfundvierzig bitte zwölf
    Uhr zwanzig' loeste keine neue Suche aus)."""
    from kern.slots import parse_slot_wish
    w = parse_slot_wish("Geht auch zwölf Uhr zwanzig?")
    assert w and w.get("hour") == 12
    w2 = parse_slot_wish("Statt zwölf Uhr fünfundvierzig bitte dreizehn Uhr.")
    assert w2 and w2.get("hour") == 13
    # "früher" ist ein RELATIVER Wunsch, keine Tageszeit (wurde als
    # "vormittags 7-12" gedeutet und warf Nachmittags-Slots weg).
    w3 = parse_slot_wish("Kann man den ein bisschen früher machen?")
    assert not (w3 and w3.get("hourMin") == 7)


def test_verschieben_gleicher_tag_frueher():
    """'Früher' beim Verschieben: Slots am SELBEN Tag VOR dem Termin werden
    angeboten (live 27.08. 15:22: 12:15 war frei, angeboten wurde erst
    Montag drauf). Daten dynamisch (morgen statt hart 28.08.) — der Test
    alterte sonst und lief ab dem 29.08. rot, weil die Slots vorbei waren."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from bianca import verwalten
    tag = datetime.now(ZoneInfo("Europe/Berlin")).replace(
        hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

    def _um(basis, h, m):
        return basis.replace(hour=h, minute=m).isoformat(timespec="seconds")

    spaeter = tag + timedelta(days=3)
    echt = verwalten.kal.find_slots
    verwalten.kal.find_slots = lambda tenant, ctx, **kw: {"ok": True, "slots": [
        _um(tag, 12, 15), _um(tag, 13, 15),
        _um(spaeter, 9, 30), _um(spaeter, 10, 0),
    ]}
    try:
        sit = _sit()
        s = gehirn.sammler(sit)
        s.update({"modus": "verschieben", "vorname": "Felix", "nachname": "Magath"})
        sit["gefunden"] = [{"id": "t1", "iso": _um(tag, 12, 45),
                           "spoken": "morgen um zwölf Uhr fünfundvierzig",
                           "calendarId": "kal1", "doctorName": "Dr. Petsas"}]
        sit["verwaltenTermin"] = "t1"
        verwalten._richtung_merken(sit, "Kann man den ein bisschen früher machen?")
        assert sit.get("verschiebRichtung") == "frueher"
        aus = verwalten._verschieb_angebot(sit, None)
        isos = [o["iso"] for o in sit.get("offered") or []]
        assert isos == [_um(tag, 12, 15)], isos
        assert "zwölf Uhr fünfzehn" in (aus.get("text") or "")
    finally:
        verwalten.kal.find_slots = echt


def test_kein_angebot_nach_verschieben():
    """Nach erledigtem Verschieben ist das Anliegen ZU: 'Das war's, danke'
    loest kein frisches Slot-Angebot mehr aus (live 27.08. 15:22)."""
    from bianca import verwalten
    echt = verwalten.kal.move_appointment
    verwalten.kal.move_appointment = lambda tenant, ctx, **kw: {
        "ok": True, "moved": True, "slotIso": kw.get("slot_iso") or "",
        "appointmentId": "t1", "spoken": "Der Termin liegt jetzt am Montag um neun Uhr dreißig.",
    }
    try:
        sit = _sit()
        s = gehirn.sammler(sit)
        s.update({"modus": "verschieben", "vorname": "Felix", "nachname": "Magath",
                  "phase": "verschieb_bestaetigen", "frage": "verschieb_ok",
                  "slotIso": "2026-08-31T09:30:00+02:00"})
        sit["gefunden"] = [{"id": "t1", "iso": "2026-08-28T12:45:00+02:00",
                           "spoken": "morgen um zwölf Uhr fünfundvierzig"}]
        sit["gefundenKey"] = "felix|magath"
        sit["verwaltenTermin"] = "t1"
        z = verwalten.zug(sit, "Ja", set())
        assert z is not None and "verschoben" in (z.get("text") or "").lower() or "liegt jetzt" in (z.get("text") or "")
        assert s["modus"] == "" and s["phase"] == "fertig" and not sit.get("offered")
        # Verabschiedung danach: kein deterministisches Angebot mehr.
        assert verwalten.zug(sit, "Das war's, danke schön.", set()) is None
    finally:
        verwalten.kal.move_appointment = echt


# --- Slot-Wahl: gesprochene Zielzeit rundet auf den nächsten Slot ----------
# Live 27.08.2026 17:40 ("Um neun Uhr vierundvierzig ist super"): die Wahl
# scheiterte, der Satz wurde als neuer Wunsch gedeutet und Bianca wiederholte
# WORTGLEICH das Angebot 09:30/09:45/10:00.

ANGEBOT_MONTAG = [
    {"iso": "2026-08-31T09:30", "spoken": "am Montag um neun Uhr dreißig"},
    {"iso": "2026-08-31T09:45", "spoken": "am Montag um neun Uhr fünfundvierzig"},
    {"iso": "2026-08-31T10:00", "spoken": "am Montag um zehn Uhr"},
]


def test_zeit_von_zusammengesetzte_minuten():
    assert flow._zeit_von(" um neun uhr vierundvierzig ") == (9, 44)
    assert flow._zeit_von(" zwölf uhr sieben ") == (12, 7)
    assert flow._zeit_von(" 9 uhr 44 ") == (9, 44)


def test_slot_wahl_rundet_auf_naechsten_slot():
    assert flow._slot_wahl("Um neun Uhr vierundvierzig ist super", ANGEBOT_MONTAG) == "2026-08-31T09:45"
    assert flow._slot_wahl("dann 9 Uhr 44", ANGEBOT_MONTAG) == "2026-08-31T09:45"


def test_slot_wahl_rundet_nicht_bei_fernen_zeiten():
    assert flow._slot_wahl("geht auch vierzehn Uhr zehn?", ANGEBOT_MONTAG) == ""


def test_angebot_wird_nicht_wiederholt_live_1740():
    """Das Live-Muster im Fluss: Angebot steht, Anrufer nennt neun Uhr
    vierundvierzig — es folgt der Readback auf 09:45, keine Wiederholung."""
    echt_anstossen = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        s = gehirn.sammler(sit)
        s.update({"modus": "buchen", "warSchonMal": True,
                  "arzt": {"typ": "genannt", "calendarId": "zex5bmv5jfIHWVW6zHbg", "calendarName": "Dr. Petsas"},
                  "vorname": "Michael", "nachname": "Petsas", "buchstabiert": True,
                  "grund": "Kontrolluntersuchung", "wunsch": {"weekday": 1, "hour": 9},
                  "telefonAkte": True, "phase": "angebot", "frage": "slotwahl"})
        sit["offered"] = list(ANGEBOT_MONTAG)
        z = flow.zug(sit, "Um neun Uhr vierundvierzig ist super")
        assert z and "halte ich fest" in z["text"].lower(), z
        assert s["slotIso"] == "2026-08-31T09:45"
    finally:
        flow.hintergrund.anstossen = echt_anstossen


def _iso_in(tage: int, h: int, m: int = 0) -> str:
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    d = datetime.now(ZoneInfo("Europe/Berlin")).replace(
        hour=h, minute=m, second=0, microsecond=0) + timedelta(days=tage)
    return d.isoformat(timespec="seconds")


def test_wiederhol_wache_sagt_gleiches_angebot_ehrlich_an():
    """Führt ein neuer Wunsch zum SELBEN Angebot, sagt Bianca das ehrlich
    ('es bleibt bei …') statt die Liste wortgleich zu wiederholen."""
    echt_anstossen = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        s = gehirn.sammler(sit)
        slot = _iso_in(30, 9, 30)
        s.update({"modus": "buchen", "warSchonMal": True,
                  "arzt": {"typ": "genannt", "calendarId": "zex5bmv5jfIHWVW6zHbg", "calendarName": "Dr. Petsas"},
                  "vorname": "Michael", "nachname": "Petsas", "buchstabiert": True,
                  "grund": "Kontrolluntersuchung", "wunsch": {},
                  "telefonAkte": True, "phase": "angebot", "frage": "slotwahl"})
        sit["slotVorrat"] = [slot]
        sit["offered"] = [{"iso": slot, "spoken": "in vier Wochen um neun Uhr dreißig"}]
        z = flow.zug(sit, "Ginge es auch nächste Woche?")
        assert z and "es bleibt bei" in z["text"], z
        assert [o["iso"] for o in sit["offered"]] == [slot]
    finally:
        flow.hintergrund.anstossen = echt_anstossen


# --- Angebots-Streuung (Chef 27.08.: nie benachbarte Leer-Slots) ------------
# Live 27.08.: angeboten wurden 12:15/12:45/13:15 bzw. 09:30/09:45/10:00 —
# am selben Tag müssen mindestens 2,5 Stunden zwischen den Angeboten liegen.

def _now_ms_test() -> int:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return int(datetime(2026, 8, 27, 12, 0, tzinfo=ZoneInfo("Europe/Berlin")).timestamp() * 1000)


DICHT = [
    "2026-08-28T12:15:00+02:00", "2026-08-28T12:45:00+02:00",
    "2026-08-28T13:15:00+02:00", "2026-08-28T15:00:00+02:00",
    "2026-08-31T09:30:00+02:00", "2026-08-31T09:45:00+02:00",
]


def _keine_nachbarn(slots: list[dict]) -> None:
    from itertools import combinations
    for a, b in combinations(slots, 2):
        if a["date"] == b["date"]:
            ta = int(a["time"][:2]) * 60 + int(a["time"][3:5])
            tb = int(b["time"][:2]) * 60 + int(b["time"][3:5])
            assert abs(ta - tb) >= 150, (a, b)


def test_streuung_keine_nachbar_slots():
    from kern.slots import pick_slots
    res = pick_slots(DICHT, now_ms=_now_ms_test())
    assert len(res["slots"]) == 3
    _keine_nachbarn(res["slots"])
    assert res["slots"][0]["iso"].startswith("2026-08-28T12:15")


def test_streuung_wunsch_nachmittag_bleibt():
    """'Morgen nachmittag' wird nicht verwässert: gestreut wird INNERHALB des
    Wunschrahmens — lieber zwei gute Optionen als drei dichte."""
    from kern.slots import pick_slots
    res = pick_slots(DICHT, wish={"date": "2026-08-28", "hourMin": 12, "hourMax": 18},
                     now_ms=_now_ms_test())
    assert res["wishMatched"]
    isos = [x["iso"] for x in res["slots"]]
    assert isos == ["2026-08-28T12:15:00+02:00", "2026-08-28T15:00:00+02:00"], isos


def test_streuung_fallback_ein_slot_plus_andere_tage():
    """Wunschtag hat NUR benachbarte Slots: EIN Slot des Tages plus
    Alternativen anderer Tage — nicht drei dichte."""
    from kern.slots import pick_slots
    vorrat = ["2026-08-28T12:15:00+02:00", "2026-08-28T12:45:00+02:00",
              "2026-08-28T13:15:00+02:00", "2026-08-31T09:30:00+02:00"]
    res = pick_slots(vorrat, wish={"date": "2026-08-28"}, now_ms=_now_ms_test())
    isos = [x["iso"] for x in res["slots"]]
    assert isos[0] == "2026-08-28T12:15:00+02:00", isos
    assert "2026-08-31T09:30:00+02:00" in isos, isos
    _keine_nachbarn(res["slots"])


def test_streuung_gar_nichts_anderes_laesst_nahe_zu():
    """Nur drei benachbarte Slots im ganzen Vorrat: besser dicht anbieten
    als gar nichts."""
    from kern.slots import pick_slots
    vorrat = ["2026-08-28T12:15:00+02:00", "2026-08-28T12:45:00+02:00",
              "2026-08-28T13:15:00+02:00"]
    res = pick_slots(vorrat, now_ms=_now_ms_test())
    assert [x["iso"] for x in res["slots"]] == vorrat


def test_streuung_notfall_bleibt_dicht():
    """Akute Beschwerden: die nächstmöglichen Plätze dicht anbieten —
    Dringlichkeit schlägt Streuung."""
    from kern.slots import pick_slots
    res = pick_slots(DICHT, now_ms=_now_ms_test(), dringend=True)
    assert [x["iso"] for x in res["slots"]] == DICHT[:3]


def test_streuung_zielzeit_anker_zuerst():
    """'Gegen zehn': der nächstliegende Slot bleibt das ERSTE Angebot."""
    from kern.slots import pick_slots
    vorrat = ["2026-08-28T09:00:00+02:00", "2026-08-28T10:05:00+02:00",
              "2026-08-28T13:00:00+02:00"]
    res = pick_slots(vorrat, wish={"hour": 10}, now_ms=_now_ms_test())
    assert res["slots"][0]["iso"].startswith("2026-08-28T10:05"), res["slots"]
    _keine_nachbarn(res["slots"])


def test_notfall_im_fluss_bietet_dicht_an():
    """Der Fluss reicht die Dringlichkeit durch: Grund 'akute Beschwerden/
    Notfall' bekommt die nächsten Slots ohne Streuung."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True,
              "arzt": {"typ": "genannt", "calendarId": "zex5bmv5jfIHWVW6zHbg", "calendarName": "Dr. Petsas"},
              "vorname": "Michael", "nachname": "Petsas", "buchstabiert": True,
              "grund": "akute Beschwerden/Notfall", "wunsch": {},
              "telefonAkte": True})
    dicht = [_iso_in(30, 12, 15), _iso_in(30, 12, 45), _iso_in(30, 13, 15)]
    sit["slotVorrat"] = list(dicht)
    flow._angebot(sit)
    assert [o["iso"] for o in sit.get("offered") or []] == dicht


def test_termin_notiz_minimal_ohne_datenkern():
    """Chef 27.08. (zweite Runde): NUR noch der eine Satz mit Grund plus
    Auffälligem — kein Datenkern, keine Kurzfassung, kein LLM."""
    sit = _sit()
    sit["stimme"] = "Bianca"
    sit["lastBook"] = {"name": "book_slot", "booked": True}
    s = gehirn.sammler(sit)
    s["grund"] = "akute Beschwerden/Notfall"
    s["grundWortlaut"] = "Ich habe ganz dolle Zahnschmerzen"
    sit["zuege"] = [
        {"textIn": "Ich habe ganz dolle Zahnschmerzen", "text": "Waren Sie schon mal bei uns?"},
        {"textIn": "Nein", "text": "Der Termin morgen um dreizehn Uhr fünfzehn ist eingetragen."},
    ]
    from kern import notes
    notiz = notes.termin_notiz(sit)
    zeilen = notiz.splitlines()
    assert zeilen[0].startswith("telefonisch Termin vereinbart wegen ")
    assert "Zahnschmerzen" in zeilen[0]
    assert zeilen[0].endswith("// Bianca")
    assert "Kurzfassung" not in notiz and "Telefonprotokoll" not in notiz
    assert "Waren Sie schon mal bei uns?" not in notiz  # kein Dialog-Wortlaut
    # "Schmerzen" ist ein Auffälligkeits-Stichwort — als Patienten-O-Ton ok:
    for zeile in zeilen[1:]:
        assert zeile.startswith("Patient erwähnt: ") and zeile.endswith("// Bianca")


# --- Chef 27.08. (Runde 3): Namen sauber trennen, Korrekturen sofort -------

def test_einzelner_vorname_wird_vorname():
    """"Paul?" auf die Namensfrage ist ein VORNAME — live wurde daraus
    'Herr Paul' (als Nachname geführt und falsch angesprochen)."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["frage"] = "name"
    gehirn.einsammeln(sit, "Paul?")
    assert s["vorname"] == "Paul" and not s["nachname"]
    fid, frage = gehirn.naechste_frage(sit)
    # Es fehlt jetzt der NACHNAME — nicht noch einmal der volle Name.
    assert s["warSchonMal"] is None or fid  # naechste_frage läuft
    s["warSchonMal"] = False
    s["arzt"] = {"typ": "egal"}
    s["grund"] = "Kontrolluntersuchung"
    s["wunsch"] = {}
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "nachname" and "Nachname" in frage


def test_explizite_vor_und_nachnamen_ansage():
    """"Nee, der Vorname ist Paul und der Nachname ist Panzer" — live wurde
    'Nee Paul' geerntet."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["frage"] = "vorname"
    s["nachname"] = "Paul"  # der falsche Stand aus dem Live-Gespräch
    gehirn.einsammeln(sit, "Nee, der Vorname ist Paul und der Nachname ist Panzer")
    assert s["vorname"] == "Paul"
    assert s["nachname"] == "Panzer"


def test_buchstabieren_frisst_keine_nachbarworte():
    """"... P-A-N-Z-E-R. Der Vorname ist Paul" ergab live 'Panzerp' — das P
    von 'Paul' (Buchstabier-Tafelwort) klebte am Namen."""
    d = buchstaben.deute("Also der Nachname ist Panzer. P-A-N-Z-E-R. Der Vorname ist Paul")
    assert d and d["name"] == "Panzer"
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["frage"] = "buchstabieren"
    gehirn.einsammeln(sit, "Also der Nachname ist Panzer. P-A-N-Z-E-R. Der Vorname ist Paul")
    assert s["nachname"] == "Panzer" and s["buchstabiert"]
    assert s["vorname"] == "Paul"


def test_buchstabieren_nachgesprochen_in_silben():
    """"MATTA VATTA" statt Buchstabierung: übernehmen statt auf dem alten
    Hörfehler ('Pidoq') zu beharren."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["frage"] = "buchstabieren"
    s["nachname"] = "Pidoq"
    gehirn.einsammeln(sit, "MATTA VATTA")
    assert s["nachname"] == "Mattavatta" and s["buchstabiert"]


def test_name_korrektur_heisse_x_nicht_y():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["vorname"], s["nachname"] = "Paul", "Müller"
    s["patientId"], s["bekannt"] = "p77", True
    gehirn.einsammeln(sit, "Das ist falsch, ich heiße Meier nicht Müller")
    assert s["nachname"] == "Meier"
    # Kartei-Treffer ist mit dem korrigierten Namen hinfällig:
    assert not s["patientId"] and not s["bekannt"]


def test_name_korrektur_nicht_x_sondern_y():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["vorname"], s["nachname"] = "Paul", "Müller"
    gehirn.einsammeln(sit, "Nicht Müller, sondern Meier")
    assert s["nachname"] == "Meier"


def test_arzt_korrektur_nicht_patrikis_sondern_petsas():
    """"Nein, nicht Dr. Patrikis — ich habe mich vertan, ich wollte zu
    Dr. Petsas": der Behandler wird SOFORT umgestellt (Chef 27.08.)."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["arzt"] = {"typ": "genannt", "calendarId": "RHYdoQFD7oAhqIepLzC2", "calendarName": "Dr. Patrikis"}
    gehirn.einsammeln(sit, "Nein, nicht Doktor Patrikis, ich habe mich vertan — ich wollte zu Doktor Petsas.")
    assert (s["arzt"] or {}).get("calendarName") == "Dr. Petsas"
    # Und der Patientennamen-Speicher bleibt unangetastet (Arzt-Kontext!):
    assert not s["nachname"]


def test_arzt_korrektur_erst_richtig_dann_verneint():
    """"Zu Petsas bitte, nicht zu Patrikis" — der verneinte Name fliegt raus."""
    from bianca import arzt as arztmod
    sit = _sit()
    d = arztmod.deute("Zu Doktor Petsas bitte, nicht zu Doktor Patrikis", sit["tenant"])
    assert d and d.get("calendarName") == "Dr. Petsas"


def test_telefon_korrektur_nummer_war_falsch():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["telefon"], s["telefonOk"] = "01776004600", True
    neu = gehirn.einsammeln(sit, "Die Nummer war falsch, die stimmt nicht.")
    assert "telefonKorrektur" in neu
    assert not s["telefon"] and not s["telefonOk"]


def test_jupp_und_hier_nein():
    assert gehirn.ist_ja("Jupp")
    assert gehirn.ist_ja("Joa, passt schon")
    assert gehirn.ist_nein("Äh, hier nein")
    assert gehirn.ist_nein("Ich glaube nein.")


def test_telefon_check_bleibt_deterministisch():
    """Unklare Antwort auf die Nummern-Rückbestätigung geht NICHT ans LLM
    (das erfand 'die habe ich notiert' und der Anker fragte doppelt)."""
    sit = _sit()
    sit["slotVorrat"] = [_iso_in(3, 9, 0), _iso_in(4, 10, 30), _iso_in(5, 14, 0)]
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": False, "grund": "Kontrolluntersuchung",
              "wunsch": {}, "vorname": "Pinocchio", "nachname": "Mattavatta",
              "buchstabiert": True, "telefonOffen": "01776004600", "frage": "telefon_check"})
    r = flow.zug(sit, "Wird schon stimmen irgendwie")
    assert r and "Stimmt die Nummer so" in r["text"]
    # Zweiter unklarer, nicht verneinender Anlauf: Nummer gilt.
    r2 = flow.zug(sit, "Mhm, wird schon stimmen")
    assert s["telefonOk"] and s["telefon"] == "01776004600"
    assert r2 and "Stimmt das so" not in (r2.get("text") or "")


def test_besuchsgrund_mapping_auf_behandlerliste():
    """Wurzelbehandlung/PZR/Reparatur werden auf die Besuchsgrund-Liste des
    Behandlers gemappt — 'klein' gewinnt, im Zweifel Kontrolle/Besprechung."""
    from bianca import besuchsgrund
    tenant = _sit()["tenant"]
    # PZR gibt es in der Liste (PRO professionelle Zahnreinigung):
    kern, vm = besuchsgrund.deute(tenant, "Ich brauche mal wieder eine Zahnreinigung")
    assert kern == "professionelle Zahnreinigung"
    assert vm and "Zahnreinigung" in vm["name"]
    # Wurzelbehandlung führt der Mandant nicht -> Zweifelsfall Kontrolle:
    kern, vm = besuchsgrund.deute(tenant, "Ich brauche eine Wurzelbehandlung")
    assert kern == "Wurzelbehandlung"
    assert vm and "Kontroll" in vm["name"]
    # Kaputte Prothese ist eine Reparatur -> hier: ZE Besprechung:
    kern, vm = besuchsgrund.deute(tenant, "Meine Prothese ist gebrochen")
    assert kern == "Reparatur Zahnersatz"
    assert vm and vm["name"] == "ZE Besprechung"


def test_besuchsgrund_klein_praeferenz():
    from bianca import besuchsgrund
    tenant = {"visitMotives": [
        {"id": "1", "name": "WK groß"},
        {"id": "2", "name": "WK klein"},
        {"id": "3", "name": "PZR"},
        {"id": "4", "name": "Reparatur (klein)"},
        {"id": "5", "name": "Reparatur (groß)"},
        {"id": "6", "name": "Kontrolltermin"},
    ]}
    kern, vm = besuchsgrund.deute(tenant, "Ich brauche eine Wurzelbehandlung")
    assert vm and vm["name"] == "WK klein"
    kern, vm = besuchsgrund.deute(tenant, "Meine Prothese ist gebrochen")
    assert vm and vm["name"] == "Reparatur (klein)"
    kern, vm = besuchsgrund.deute(tenant, "Einmal Zahnreinigung bitte")
    assert vm and vm["name"] == "PZR"


def test_grund_wortlaut_landet_im_sammler():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["frage"] = "grund"
    gehirn.einsammeln(sit, "Ich wollte mir die Fingernägel lackieren lassen")
    assert s["grundWortlaut"].startswith("Ich wollte mir die Fingernägel")
    assert s["motivName"]  # Zweifelsfall-Motiv ist gesetzt


def test_wiederhol_wache_streicht_gefuellte_fragen():
    from bianca import agent as bagent
    s = {"telefonOk": True, "vorname": "Paul", "nachname": "Panzer",
         "arzt": {"typ": "genannt", "calendarId": "x"}, "grund": "Kontrolle",
         "warSchonMal": True, "buchstabiert": True, "wunsch": {}}
    text = ("Das kläre ich gern. Unter welcher Handynummer erreichen wir Sie? "
            "Und bei welchem Behandler waren Sie zuletzt?")
    raus = bagent._gefuellte_fragen_streichen(s, text)
    assert "Handynummer" not in raus and "Behandler" not in raus
    assert raus.startswith("Das kläre ich gern.")


def test_bestaetigung_unklar_bleibt_deterministisch():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "phase": "bestaetigen", "frage": "bestaetigung",
              "warSchonMal": False, "grund": "Kontrolluntersuchung", "wunsch": {},
              "vorname": "Paul", "nachname": "Panzer", "buchstabiert": True,
              "telefon": "01776004600", "telefonOk": True,
              "slotIso": "2026-09-02T09:00:00+02:00"})
    sit["offered"] = [{"iso": "2026-09-02T09:00:00+02:00", "spoken": "am Mittwoch um neun"}]
    r = flow.zug(sit, "Hmpf, von mir aus halt")
    # "von mir aus" ist eine Kurz-Zustimmung — sonst deterministische Rückfrage.
    assert r is not None


def test_egal_auf_die_zeitfrage_ist_eine_antwort():
    """Live 29.08.2026: 'Das ist mir egal.' auf die Wunschzeit-Frage ging ans
    LLM, das eine Kalender-Störung erfand — erst das zweite 'egal' löste über
    die Eskalation auf. 'Egal' zählt jetzt sofort als 'keine Präferenz'."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": False,
              "grund": "akute Beschwerden/Notfall", "frage": "wunsch"})
    neu = gehirn.einsammeln(sit, "Das ist mir egal.")
    assert "wunsch" in neu and s["wunsch"] == {}

    # Mit Arzt-Bezug ("Egal welcher Arzt") bleibt die Zeitfrage offen —
    # das Egal gehört dem Behandler-Deuter.
    sit2 = _sit()
    s2 = gehirn.sammler(sit2)
    s2.update({"modus": "buchen", "warSchonMal": True, "frage": "wunsch"})
    gehirn.einsammeln(sit2, "Egal welcher Arzt.")
    assert s2["wunsch"] is None

    # Ohne offene Zeitfrage bleibt "egal" folgenlos für den Wunsch.
    sit3 = _sit()
    s3 = gehirn.sammler(sit3)
    s3.update({"modus": "buchen", "frage": "grund"})
    gehirn.einsammeln(sit3, "Das ist mir egal.")
    assert s3["wunsch"] is None


# --- Behandler-Wahl fuer Neupatienten (Chef 29.08.2026) ---------------------

def test_neupatient_bekommt_behandler_wahl():
    """Chef 29.08.2026: 'es muss zu beginn geklärt werden in welchem kalender
    und bei welchem arzt du suchen sollst' — Neupatienten wurden nie gefragt,
    die Suche lief stumm ohne Behandler-Klärung."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": False})
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "arzt"
    for name in ("Petsas", "Nikolaou", "Patrikis"):
        assert name in frage, f"alle Behandler zur Wahl anbieten: {frage}"
    assert "zuletzt" not in frage.lower(), "Neupatient war nie da"

    # Antwort mit Namen: Kalender des Genannten, dann weiter zum Anliegen.
    s["frage"] = "arzt"
    neu = gehirn.einsammeln(sit, "Am liebsten zu Doktor Nikolaou.")
    assert "arzt" in neu and "Nikolaou" in (s["arzt"] or {}).get("calendarName", "")
    assert s["warSchonMal"] is False, "Behandler-Wunsch macht niemanden zum Bestandspatienten"
    fid2, _ = gehirn.naechste_frage(sit)
    assert fid2 == "grund"


def test_neupatient_egal_laesst_global_suchen():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": False, "frage": "arzt"})
    neu = gehirn.einsammeln(sit, "Das ist mir egal.")
    assert "arzt" in neu and (s["arzt"] or {}).get("typ") == "egal"
    fid, _ = gehirn.naechste_frage(sit)
    assert fid == "grund", "nach 'egal' geht es normal weiter"


def test_bestand_behandlerfrage_bleibt_zuletzt():
    """Regression: Bestandspatienten behalten die Akten-Frage nach dem
    LETZTEN Behandler — nur Neupatienten bekommen die Wahl-Frage."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True})
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "arzt" and "zuletzt" in frage


def test_arztwahl_formen_tragen_kernwort():
    """Kern-Wort-Regel wie fuer FRAGE_VARIANTEN: Anker und Wachen muessen
    die offene Frage an 'Behandler' erkennen (agent._FRAGE_KERN['arzt'])."""
    import re

    from bianca import agent as bianca_agent

    kern = bianca_agent._FRAGE_KERN["arzt"]
    tenant = laden("meddent")
    formen = list(gehirn.ARZTWAHL_VARIANTEN) + [
        gehirn.arztwahl_frage(tenant), gehirn.arztwahl_frage(None),
    ]
    for form in formen:
        assert re.search(kern, form, re.I), f"Form ohne Kern-Wort: {form}"


def test_wiederholte_arztwahl_nimmt_wahl_variante():
    """Muss die Wahl-Frage wiederholt werden, kommt eine WAHL-Formulierung —
    nie 'bei wem waren Sie zuletzt?' (der Anrufer war nie da)."""
    from bianca import agent as bianca_agent

    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": False, "frage": "arzt"})
    frage = gehirn.arztwahl_frage(sit["tenant"])
    sit["messages"].append({"role": "assistant", "content": f"Gern. {frage}"})
    raus = bianca_agent._wiederholungs_wache(sit, f"Alles klar. {frage}")
    assert frage not in raus, "nie zweimal wortgleich"
    assert "zuletzt" not in raus.lower(), "Bestand-Formulierung waere sachlich falsch"
    assert "ehandler" in raus, "die Frage muss hoerbar bleiben (Kern-Wort)"


def test_feste_saetze_waermen_die_arztwahl():
    tenant = laden("meddent")
    saetze = gehirn.feste_saetze(tenant)
    assert gehirn.arztwahl_frage(tenant) in saetze
    for v in gehirn.ARZTWAHL_VARIANTEN:
        assert v in saetze


# --- W-TEMPO: adaptive Stille-Schwelle (Chef 29.08.2026: "300 ms schneller") -

def test_stille_ms_nach_fragetyp():
    """Ja/Nein-/Wahlfragen erwarten kurze Antworten (350 ms Ruhe reichen),
    Ziffern-/Buchstabier-Diktate brauchen Denkpausen (650 ms), sonst 500."""
    assert gehirn.stille_ms({"frage": "schonmal"}) == 350
    assert gehirn.stille_ms({"frage": "arzt"}) == 350
    assert gehirn.stille_ms({"frage": "telefon_check"}) == 350
    assert gehirn.stille_ms({"frage": "pzr"}) == 350
    assert gehirn.stille_ms({"frage": "telefon"}) == 650
    assert gehirn.stille_ms({"frage": "buchstabieren"}) == 650
    assert gehirn.stille_ms({"frage": "grund"}) == 500
    assert gehirn.stille_ms({"frage": "name"}) == 500
    assert gehirn.stille_ms({"frage": ""}) == 500
    assert gehirn.stille_ms({}) == 500


def test_dienst_traegt_stille_feld():
    """Der Dienst haengt stilleMs nur an, wenn ein stille_fn konfiguriert
    ist — Lisa (ohne Hook) bleibt byte-identisch."""
    from kern.dienst import Dienst

    mit = Dienst(name="t", start_fn=lambda sit: {}, turn_fn=lambda sit, t, **k: {},
                 stille_fn=lambda sit: gehirn.stille_ms(gehirn.sammler(sit)))
    sit = _sit()
    gehirn.sammler(sit)["frage"] = "schonmal"
    assert mit._stille_feld(sit) == {"stilleMs": 350}

    ohne = Dienst(name="t2", start_fn=lambda sit: {}, turn_fn=lambda sit, t, **k: {})
    assert ohne._stille_feld(sit) == {}


def test_readback_text_ist_dreisatzform():
    """P1 Readback-Parallelisierung: Vorsatz und Schlussfrage sind eigene,
    warmbare Saetze (in feste_saetze), der Ziffern-Satz beginnt GROSS —
    nur so trennt der Satz-Split in stimme_stream ihn vom Vorsatz ab."""
    t = gehirn.readback_text("01776004600")
    saetze = re.split(r"(?<=[.!?]) +(?=[A-ZÄÖÜ])", t)
    assert saetze[0] == "Ich wiederhole die Nummer."
    assert saetze[-1] == "Stimmt das so?"
    assert saetze[1].startswith("Null eins sieben sieben")
    fest = gehirn.feste_saetze()
    assert saetze[0] in fest and saetze[-1] in fest
