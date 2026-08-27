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
