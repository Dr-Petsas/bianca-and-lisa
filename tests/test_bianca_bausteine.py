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
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    echt_anstossen = flow.hintergrund.anstossen
    echt_find = flow.kal.find_slots
    flow.hintergrund.anstossen = lambda sit: None
    # Slots dynamisch in der Zukunft ("nächste Woche vormittags" passt):
    def _slot(tage: int, h: int, m: int) -> str:
        d = datetime.now(ZoneInfo("Europe/Berlin")).replace(
            hour=h, minute=m, second=0, microsecond=0) + timedelta(days=tage)
        return d.isoformat(timespec="seconds")
    flow.kal.find_slots = lambda *a, **k: {
        "ok": True,
        "slots": [_slot(7, 9, 15), _slot(8, 10, 30), _slot(9, 11, 0)],
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
    """Vorfall 27.08.2026: Angebot kam aus Kalender A, die späte Kartei-
    Recherche stellte den Sammler auf Kalender B um — gebucht wurde der Slot
    dann im falschen Kalender. Die Buchung MUSS am Angebots-Kalender kleben.
    Seit W-ARZT-DEFAULT (03.09.2026) sucht 'weiß nicht, bei wem ich war' ohne
    Kartei-Treffer beim Standard-Behandler (Dr. Petsas) statt global."""
    echt_anstossen = flow.hintergrund.anstossen
    echt_find = flow.kal.find_slots
    flow.hintergrund.anstossen = lambda sit: None
    flow.kal.find_slots = lambda *a, **k: {
        "ok": True,
        "slots": [_iso_in(5, 9, 0), _iso_in(5, 9, 15), _iso_in(6, 9, 30)],
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
        # W-ARZT-DEFAULT: ungeklaerter Behandler -> Standard-Kalender Petsas.
        assert bind.get("calendarId") == "zex5bmv5jfIHWVW6zHbg", bind
        assert "M.Sc" not in (z["text"] or "")

        # Späte Kartei-Recherche stellt den Sammler um — darf die Buchung
        # nicht mehr umlenken:
        s["arzt"] = {"typ": "letzter", "calendarId": "RHYdoQFD7oAhqIepLzC2", "calendarName": "Dr. Patrikis"}
        ctx = flow._ctx_bauen(sit)
        assert ctx["calendarId"] == "zex5bmv5jfIHWVW6zHbg", ctx
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


def test_auskunft_erkennung_vergessener_termin():
    """Live 29.08.2026 (09:34): 'ich habe nächste Woche Dienstag einen
    Termin, aber ich weiss nicht mehr, ...' lief in die NEUBUCHUNG
    (schonmal-Frage) statt in die Termin-Auskunft."""
    sit = _sit()
    gehirn.einsammeln(sit, "Ich sagte, ich habe nächste Woche Dienstag einen "
                           "Termin, aber ich weiss nicht mehr, wann genau.")
    assert gehirn.sammler(sit)["modus"] == "auskunft"

    # Feststellung mit Zeitangabe reicht: der Termin EXISTIERT schon.
    sit2 = _sit()
    gehirn.einsammeln(sit2, "Guten Tag, ich habe nächste Woche Dienstag einen Termin.")
    assert gehirn.sammler(sit2)["modus"] == "auskunft"

    sit3 = _sit()
    gehirn.einsammeln(sit3, "Ich weiß nicht mehr, wann mein Termin ist.")
    assert gehirn.sammler(sit3)["modus"] == "auskunft"

    # Mitten in der angelaufenen Buchung rettet der Satz noch um:
    sit4 = _sit()
    gehirn.einsammeln(sit4, "Ich brauche einen Termin.")
    assert gehirn.sammler(sit4)["modus"] == "buchen"
    gehirn.einsammeln(sit4, "Nein — ich habe nächste Woche einen Termin, "
                            "aber ich weiss nicht mehr,")
    assert gehirn.sammler(sit4)["modus"] == "auskunft"


def test_auskunft_erkennung_wunsch_bleibt_buchung():
    """Wunsch-Sätze mit 'ich habe ... Termin' sind weiter NEUBUCHUNG."""
    for satz in (
        "Ich hätte gern nächste Woche einen Termin.",
        "Ich habe nächste Woche Zeit für einen Termin.",
        "Ich habe nächste Woche Urlaub und brauche einen Termin.",
        "Ich habe seit Tagen Zahnschmerzen und brauche morgen einen Termin.",
        "Haben Sie am Montag einen Termin frei?",
    ):
        sit = _sit()
        gehirn.einsammeln(sit, satz)
        assert gehirn.sammler(sit)["modus"] == "buchen", satz


def test_absage_im_angebot_bleibt_buchung():
    """'Absagen'/'verschieben' waehrend ein Buchungs-Angebot offen ist, meint
    das Angebot — der Modus darf nicht in die Bestandsverwaltung kippen."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "phase": "angebot"})
    gehirn.einsammeln(sit, "Nee, das passt nicht — dann sagen Sie es ab.")
    assert s["modus"] == "buchen"


def test_absage_fluss_komplett():
    """W-NACHNAME 31.08.2026 (phone_agent-Vorbild): NUR der Nachname wird
    erfragt, dann wird SOFORT gesucht -> Treffer bestaetigen MIT Anrede ->
    bei Ja loeschen. Keine Wann-/Behandler-Vorabfrage mehr."""
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
        assert z1 and "wie ist ihr nachname" in z1["text"].lower()
        assert "buchstabieren" in z1["text"].lower()  # direkt einladen (31.08.)
        assert "vor- und nachname" not in z1["text"].lower()
        assert gehirn.sammler(sit)["frage"] == "nachname"

        z2 = flow.zug(sit, "Martin Berger.")
        assert z2 and "wirklich absagen" in z2["text"].lower()
        assert "Herr Berger" in z2["text"]  # Anrede: "… Herr Berger?"
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


def test_absage_nachname_buchstabiert_geht_direkt_in_suche():
    """Die Absage-Frage laedt zum Buchstabieren ein (31.08.) — eine
    buchstabierte Antwort ('B E R G E R') wird gedeutet und SOFORT gesucht."""
    echt_find = verwalten.kal.find_patient_appointments
    gesucht = []
    def _find(t, c):
        gesucht.append(dict(c))
        return dict(GEFUNDEN)
    verwalten.kal.find_patient_appointments = _find
    try:
        sit = _sit()
        z1 = flow.zug(sit, "Ich möchte meinen Termin absagen.")
        assert z1 and "buchstabieren" in z1["text"].lower()
        z2 = flow.zug(sit, "B E R G E R.")
        assert z2 and "wirklich absagen" in z2["text"].lower(), z2
        assert gesucht[-1].get("lastName") == "Berger"
    finally:
        verwalten.kal.find_patient_appointments = echt_find


def test_absage_mehrere_patienten_gleicher_nachname():
    """W-NACHNAME 31.08.2026: melden sich MEHRERE Patienten mit gleichem
    Nachnamen (CF 409/ambiguous), grenzt der Vorname ab — erst dann wird
    mit firstName erneut gesucht (wie im alten phone_agent)."""
    echt_find = verwalten.kal.find_patient_appointments
    gesucht = []
    def _find(t, c):
        gesucht.append(dict(c))
        if not c.get("firstName"):
            return {"ok": True, "mehrdeutig": True, "patient": {}, "appointments": []}
        return dict(GEFUNDEN)
    verwalten.kal.find_patient_appointments = _find
    try:
        sit = _sit()
        z1 = flow.zug(sit, "Ich möchte meinen Termin absagen.")
        assert z1 and "wie ist ihr nachname" in z1["text"].lower()

        z2 = flow.zug(sit, "Berger.")
        assert z2 and "mehrere patienten" in z2["text"].lower()
        assert "vorname" in z2["text"].lower()
        assert gehirn.sammler(sit)["frage"] == "vorname"
        assert not gesucht[-1].get("firstName")  # erste Suche: nur Nachname

        z3 = flow.zug(sit, "Martin.")
        assert z3 and "wirklich absagen" in z3["text"].lower()
        assert gesucht[-1].get("firstName") == "Martin"
        assert gesucht[-1].get("lastName") == "Berger"
    finally:
        verwalten.kal.find_patient_appointments = echt_find


def test_absage_hinweis_im_einstiegssatz_filtert():
    """'Termin am Donnerstag absagen': die Zeitangabe wird als Hinweis
    geerntet und filtert die Treffer — gefragt wird trotzdem NUR der
    Nachname (W-NACHNAME)."""
    echt_find = verwalten.kal.find_patient_appointments
    verwalten.kal.find_patient_appointments = lambda t, c: dict(GEFUNDEN)
    try:
        sit = _sit()
        z1 = flow.zug(sit, "Ich muss meinen Termin am Donnerstag absagen.")
        assert z1 and "wie ist ihr nachname" in z1["text"].lower()
        assert (sit.get("verwHinweis") or {}).get("weekday") == 4  # Donnerstag
        s = gehirn.sammler(sit)
        assert not s["wunsch"]  # die Zeitangabe ist KEIN Neubuchungs-Wunsch

        z2 = flow.zug(sit, "Martin Berger.")
        assert z2 and "wirklich absagen" in z2["text"].lower()
    finally:
        verwalten.kal.find_patient_appointments = echt_find


def test_absage_name_im_einstiegssatz_sucht_sofort():
    """Nennt der Anrufer den Namen schon im Einstiegssatz, wird NICHTS
    mehr gefragt — direkt suchen (W-NACHNAME)."""
    echt_find = verwalten.kal.find_patient_appointments
    verwalten.kal.find_patient_appointments = lambda t, c: dict(GEFUNDEN)
    try:
        sit = _sit()
        z = flow.zug(sit, "Ich möchte meinen Termin absagen, mein Name ist Martin Berger.")
        assert z and "wirklich absagen" in z["text"].lower()
    finally:
        verwalten.kal.find_patient_appointments = echt_find


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


def test_termin_auskunft_statt_schonmal_frage():
    """Der echte Fehllauf 29.08.: Bianca fragte 'Waren Sie schon einmal bei
    uns?' statt in den Kalender zu schauen und den Termin vorzulesen."""
    echt_find = verwalten.kal.find_patient_appointments
    verwalten.kal.find_patient_appointments = lambda t, c: dict(GEFUNDEN)
    try:
        sit = _sit()
        z1 = flow.zug(sit, "Hallo, ich habe nächste Woche Dienstag einen "
                           "Termin, aber ich weiss nicht mehr, wann genau.")
        assert z1 and "kalender schauen" in z1["text"].lower()  # Namensfrage
        assert "schon einmal" not in z1["text"].lower()
        assert gehirn.sammler(sit)["modus"] == "auskunft"
        z2 = flow.zug(sit, "Martin Berger.")
        assert z2 and "nächster termin" in z2["text"].lower()
        assert "Petsas" in z2["text"]
    finally:
        verwalten.kal.find_patient_appointments = echt_find


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
    """Verschieben: GLEICHE Prozedur (W-NACHNAME: Nachname -> suchen),
    dann Bestaetigung des Fundes und die Neu-Wunsch-Strecke."""
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
        assert z1 and "wie ist ihr nachname" in z1["text"].lower()

        z2 = flow.zug(sit, "Martin Berger.")
        assert z2 and "gefunden" in z2["text"].lower() and "besser" in z2["text"].lower()
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


def test_verschieben_alt_neu_trennung():
    """'Termin AM Donnerstag AUF Freitag verschieben': das am-Stueck ist der
    Bestandstermin (Hinweis), das auf-Stueck bleibt der Neu-Wunsch."""
    echt_find = verwalten.kal.find_patient_appointments
    echt_slots = verwalten.kal.find_slots
    verwalten.kal.find_patient_appointments = lambda t, c: dict(GEFUNDEN)
    verwalten.kal.find_slots = lambda t, c, **k: {
        "ok": True,
        "slots": ["2026-09-08T14:30", "2026-09-11T09:30", "2026-09-11T15:00"],
        "doctorName": "Dr. Petsas",
    }
    try:
        sit = _sit()
        z1 = flow.zug(sit, "Ich möchte meinen Termin am Donnerstag auf Freitag verschieben.")
        assert z1 and "wie ist ihr nachname" in z1["text"].lower()
        assert (sit.get("verwHinweis") or {}).get("weekday") == 4   # alt: Donnerstag
        s = gehirn.sammler(sit)
        assert (s["wunsch"] or {}).get("weekday") == 5              # neu: Freitag

        z2 = flow.zug(sit, "Martin Berger.")
        # Wunsch liegt vor -> direkt Angebot, gefiltert auf Freitag (11.09.).
        assert z2 and sit.get("offered"), z2
        assert all(o["iso"].startswith("2026-09-11") for o in sit["offered"])
    finally:
        verwalten.kal.find_patient_appointments = echt_find
        verwalten.kal.find_slots = echt_slots


def test_verwaltung_kein_termin_gefunden():
    """Nicht gefunden -> ERST die Korrektur-Chance (W-NAMESKORREKTUR), dann
    ehrlich + ECHTE Notiz 'die wird Doktor X vorgelegt'; ein im Einstiegssatz
    genannter Behandler wird dabei genannt (W-NACHNAME: keine Behandler-
    Vorabfrage mehr, freiwillige Angaben zaehlen weiter)."""
    echt_find = verwalten.kal.find_patient_appointments
    verwalten.kal.find_patient_appointments = lambda t, c: {"ok": True, "notFound": True, "patient": {}, "appointments": []}
    try:
        sit = _sit()
        z1 = flow.zug(sit, "Ich möchte meinen Termin bei Doktor Petsas absagen.")
        assert z1 and "wie ist ihr nachname" in z1["text"].lower()
        assert "Petsas" in ((gehirn.sammler(sit)["arzt"] or {}).get("calendarName") or "")

        z2 = flow.zug(sit, "Martin Berger.")
        assert z2, "Antwort fehlt"
        # ERSTER Fehlschlag: nicht aufgeben — der Nachname war womoeglich
        # verhoert, der Anrufer darf ihn korrigieren (W-NAMESKORREKTUR).
        assert "falsch verstanden" in z2["text"].lower(), z2
        assert "notiz" not in z2["text"].lower()

        z3 = flow.zug(sit, "Berger.")
        assert z3, "Antwort fehlt"
        tl = z3["text"].lower()  # ZWEITER Fehlschlag: jetzt ehrlich + Notiz
        assert "ehrlich" in tl and "notiz" in tl and "vorgelegt" in tl
        assert "Doktor Petsas" in z3["text"]  # dem Behandler XY wird das vorgelegt
        assert "neuen termin" in tl  # Ausweg bleibt offen
        # Die Notiz ist ECHT (Sitzung + praxis_notizen.jsonl), kein Versprechen:
        assert "Berger" in (sit.get("praxisNotiz") or "")
        assert "nicht gefunden" in (sit.get("praxisNotiz") or "")
    finally:
        verwalten.kal.find_patient_appointments = echt_find


def test_absage_varianten_erkannt():
    """Chef 29.08. (Peter-Müller-Gespräch): 'meinen Termin absagen /
    stornieren / löschen' — die sprachlichen Varianten muessen ALLE in den
    Absage-Modus fuehren (die Nachnamen-Frage ist der Beleg)."""
    for satz in [
        "Ich möchte meinen Termin stornieren.",
        "Bitte löschen Sie meinen Termin.",
        "Können Sie den Termin streichen?",
        "Ich muss den Termin leider canceln.",
        "Mein Termin fällt aus.",
        "Ich möchte den Termin rückgängig machen.",
        "Nehmen Sie den Termin bitte aus dem Kalender, also entfernen.",
        "Ich muss den Termin platzen lassen.",
        "Ich kann den Termin nicht wahrnehmen.",
        "Den Termin bitte wieder weg.",
        "Können Sie ihn wieder stornieren?",
    ]:
        sit = _sit()
        z = flow.zug(sit, satz)
        assert gehirn.sammler(sit)["modus"] == "absagen", satz
        assert z and "wie ist ihr nachname" in z["text"].lower(), f"{satz}: {z}"
    # Auch mit Zeitangabe im Einstiegssatz bleibt es bei der Nachnamen-Frage:
    sit = _sit()
    z = flow.zug(sit, "Der Termin morgen fällt leider aus.")
    assert gehirn.sammler(sit)["modus"] == "absagen"
    assert z and "wie ist ihr nachname" in z["text"].lower(), z


def test_absage_verben_ohne_termin_bezug_zuenden_nicht():
    """Allerwelts-Verben ohne Termin-Bezug sind KEINE Absage."""
    for satz in [
        "Können Sie meine alte Nummer löschen?",
        "Mir fällt ständig die Füllung raus, ich brauche einen Termin.",
    ]:
        sit = _sit()
        flow.zug(sit, satz)
        assert gehirn.sammler(sit)["modus"] != "absagen", satz


def test_absage_neustart_nach_notfound_mit_namenskorrektur():
    """Live 29.08. 08:47 (Peter Müller): STT hoerte 'Peter Möbel', die Suche
    scheiterte ehrlich — dann wurde 'Nein, ich möchte meinen Termin absagen,
    Peter Müller.' vom Nein-Zweig der Neubuchungs-Frage verschluckt ('Alles
    klar.') und das nackte 'Ich möchte meinen Termin absagen.' fiel ans LLM
    ('Welchen Termin soll ich absagen?'). Jetzt: die Prozedur startet neu,
    und der verhoerte Name wird frisch erfragt (W-NACHNAME: nur Nachname)."""
    echt_find = verwalten.kal.find_patient_appointments
    gesucht = []
    def _find(t, c):
        gesucht.append(dict(c))
        return {"ok": True, "notFound": True, "patient": {}, "appointments": []}
    verwalten.kal.find_patient_appointments = _find
    try:
        sit = _sit()
        z1 = flow.zug(sit, "Ich würde gerne meinen Termin absagen.")
        assert z1 and "wie ist ihr nachname" in z1["text"].lower()
        z2 = flow.zug(sit, "Peter Möbel.")
        # Erster Fehlschlag: Korrektur-Chance statt Notiz (W-NAMESKORREKTUR).
        assert z2 and "falsch verstanden" in z2["text"].lower()
        assert gesucht[-1].get("lastName") == "Möbel"
        # Anrufer beharrt (STT hoert dasselbe): ZWEITER Fehlschlag -> Notiz.
        z3 = flow.zug(sit, "Peter Möbel.")
        assert z3 and "ehrlich" in z3["text"].lower() and "notiz" in z3["text"].lower()
        # Anrufer verneint die Neubuchung UND wiederholt das Anliegen im
        # selben Satz — das darf NICHT im Nein-Zweig verschluckt werden:
        z4 = flow.zug(sit, "Nein, ich möchte meinen Termin absagen, Peter Müller.")
        assert z4, "Zug darf nicht ans LLM fallen"
        assert "sonst noch etwas" not in z4["text"].lower()
        assert "wie ist ihr nachname" in z4["text"].lower()
        s = gehirn.sammler(sit)
        assert not s["nachname"], "verhoerter Name muss raus sein"
        # Frischer Anlauf: der neue Name wird direkt gesucht.
        z5 = flow.zug(sit, "Peter Müller.")
        assert z5 and gesucht[-1].get("lastName") == "Müller"
    finally:
        verwalten.kal.find_patient_appointments = echt_find


def test_absage_korrektur_chance_nach_erstem_fehlschlag():
    """Live 31.08. 10:33 (Zannes): STT hoerte 'Sannes Czannis', die Suche
    scheiterte — und Bianca gab SOFORT auf (Notiz + Neubuchungs-Frage).
    Chef: 'der patient muss zumindest einmal die moeglichkeit haben den
    nachnamen zu korrigieren.' Jetzt: erste Fehlsuche -> Korrektur-Frage;
    die explizite Korrektur wird geerntet und SOFORT neu gesucht — und der
    Vorname aus der verhoerten Aeusserung fliegt mit raus."""
    echt_find = verwalten.kal.find_patient_appointments
    gesucht = []
    def _find(t, c):
        gesucht.append(dict(c))
        if c.get("lastName") == "Zannes":
            return dict(GEFUNDEN)
        return {"ok": True, "notFound": True, "patient": {}, "appointments": []}
    verwalten.kal.find_patient_appointments = _find
    try:
        sit = _sit()
        z1 = flow.zug(sit, "Hallo, ich muss meinen Termin leider absagen.")
        assert z1 and "wie ist ihr nachname" in z1["text"].lower()

        z2 = flow.zug(sit, "Sannes Czannis.")
        assert z2 and "falsch verstanden" in z2["text"].lower(), z2
        assert "notiz" not in z2["text"].lower(), "nie beim ersten Fehlschlag aufgeben"
        assert gesucht[-1].get("lastName") == "Czannis"

        z3 = flow.zug(sit, "Nein, mein Nachname ist Zannes.")
        assert z3 and "wirklich absagen" in z3["text"].lower(), z3
        assert gesucht[-1].get("lastName") == "Zannes"
        # Der Vorname 'Sannes' stammte aus derselben verhoerten Aeusserung —
        # er darf die korrigierte Suche nicht vergiften:
        assert gesucht[-1].get("firstName") != "Sannes"
    finally:
        verwalten.kal.find_patient_appointments = echt_find


def test_absage_korrektur_am_nein_zweig_vorbei():
    """Live 31.08. 10:33, dritter Zug: 'Nein, mein Nachname ist Zannes.' auf
    die Neubuchungs-Frage bekam 'Alles klar.' — die Korrektur versank im
    Nein-Zweig. Jetzt wird die explizite Zuweisung IMMER geerntet und der
    frische Name direkt gesucht (W-NAMESKORREKTUR)."""
    echt_find = verwalten.kal.find_patient_appointments
    gesucht = []
    def _find(t, c):
        gesucht.append(dict(c))
        if c.get("lastName") == "Zannes":
            return dict(GEFUNDEN)
        return {"ok": True, "notFound": True, "patient": {}, "appointments": []}
    verwalten.kal.find_patient_appointments = _find
    try:
        sit = _sit()
        flow.zug(sit, "Ich muss meinen Termin absagen.")
        flow.zug(sit, "Sannes Czannis.")       # 1. Fehlschlag -> Korrektur-Frage
        z = flow.zug(sit, "Tschannis.")        # 2. Fehlschlag -> Notiz + Neubuchung?
        assert z and "notiz" in z["text"].lower()
        assert gehirn.sammler(sit)["frage"] == "neubuchung"

        z2 = flow.zug(sit, "Nein, mein Nachname ist Zannes.")
        assert z2, "Korrektur darf nicht ans LLM fallen"
        assert "alles klar" not in z2["text"].lower(), "Nein-Zweig hat die Korrektur verschluckt"
        assert "wirklich absagen" in z2["text"].lower(), z2
        assert gesucht[-1].get("lastName") == "Zannes"
    finally:
        verwalten.kal.find_patient_appointments = echt_find


def test_vorname_verworfen_kartei_schlaegt_verhoer():
    """W-NAMESKORREKTUR: meldet die Suche vornameVerworfen (Treffer kam erst
    ohne firstName), gilt der Vorname aus der KARTEI — nicht das Verhoerte.
    Bei mehrdeutig+vornameVerworfen wird der Vorname geleert und gefragt."""
    echt_find = verwalten.kal.find_patient_appointments
    treffer = dict(GEFUNDEN)
    treffer["vornameVerworfen"] = True
    verwalten.kal.find_patient_appointments = lambda t, c: dict(treffer)
    try:
        sit = _sit()
        flow.zug(sit, "Ich möchte meinen Termin absagen.")
        z = flow.zug(sit, "Sannes Berger.")
        assert z and "wirklich absagen" in z["text"].lower()
        assert gehirn.sammler(sit)["vorname"] == "Martin"  # aus der Kartei
    finally:
        verwalten.kal.find_patient_appointments = echt_find

    # mehrdeutig + vornameVerworfen: der gespeicherte Vorname passte nicht —
    # leeren und den Vornamen ehrlich erfragen statt sofort aufzugeben.
    verwalten.kal.find_patient_appointments = lambda t, c: {
        "ok": True, "mehrdeutig": True, "vornameVerworfen": True,
        "patient": {}, "appointments": [],
    }
    try:
        sit = _sit()
        flow.zug(sit, "Ich möchte meinen Termin absagen.")
        z = flow.zug(sit, "Sannes Berger.")
        assert z and "vorname" in z["text"].lower(), z
        s = gehirn.sammler(sit)
        assert s["frage"] == "vorname" and not s["vorname"]
    finally:
        verwalten.kal.find_patient_appointments = echt_find


def test_find_patient_appointments_nachfass_ohne_vorname():
    """kern.calendar: 404 MIT firstName loest genau EINEN Nachfass-Versuch
    NUR mit dem Nachnamen aus (der Vorname kann selbst verhoert sein) —
    die Antwort traegt dann vornameVerworfen (W-NAMESKORREKTUR)."""
    echt = verwalten.kal._cf_post
    calls = []
    def _post(route, body, **kw):
        calls.append(dict(body))
        if body.get("firstName"):
            return 404, {"status": "not_found"}
        return 200, {"status": "success",
                     "patient": {"id": "p1", "firstName": "Georgios", "lastName": "Zannes"},
                     "appointments": []}
    verwalten.kal._cf_post = _post
    try:
        res = verwalten.kal.find_patient_appointments(
            {"clientId": "c", "locationId": "l"},
            {"firstName": "Sannes", "lastName": "Zannes"},
        )
        assert res.get("ok") and res.get("vornameVerworfen"), res
        assert (res.get("patient") or {}).get("firstName") == "Georgios"
        assert len(calls) == 2 and "firstName" not in calls[-1]
    finally:
        verwalten.kal._cf_post = echt


def test_wiederholte_wann_frage_nimmt_variante():
    """W-ABSAGE-NEUSTART: startet die Sammel-Prozedur im selben Anruf neu,
    darf der Wiederholungs-Wächter die Wann-Frage nicht streichen — live
    29.08. blieb sonst nur 'Das machen wir.' übrig. Es kommt die nächste
    Formulierung mit denselben Kern-Wörtern."""
    import re

    from bianca import agent as bianca_agent

    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "absagen", "frage": "wann"})
    frage = ("Das machen wir. Wann ist der Termin denn — "
             "zum Beispiel der Wochentag oder die Uhrzeit?")
    sit["messages"].append({"role": "assistant", "content": frage})
    raus = bianca_agent._wiederholungs_wache(sit, frage)
    assert "zum beispiel der wochentag" not in raus.lower(), "nie zweimal wortgleich"
    assert re.search(bianca_agent._FRAGE_KERN["wann"], raus, re.I), \
        f"Wann-Frage muss hoerbar bleiben: {raus!r}"


def test_absage_wiederholt_nach_abschluss_startet_neu():
    """Nach 'Alles klar.' (bares Nein auf die Neubuchungs-Frage) muss ein
    erneutes 'Ich möchte meinen Termin absagen.' die Prozedur NEU starten —
    frueher klebte modus auf 'absagen' und nichts passierte."""
    echt_find = verwalten.kal.find_patient_appointments
    verwalten.kal.find_patient_appointments = lambda t, c: {"ok": True, "notFound": True, "patient": {}, "appointments": []}
    try:
        sit = _sit()
        flow.zug(sit, "Ich möchte meinen Termin absagen.")
        z = flow.zug(sit, "Kasimir Probefall.")
        assert z and "falsch verstanden" in z["text"].lower()  # Korrektur-Chance
        z2 = flow.zug(sit, "Probefall.")
        assert z2 and "notiz" in z2["text"].lower()  # zweiter Fehlschlag
        z3 = flow.zug(sit, "Nein.")
        assert z3 and "sonst noch etwas" in z3["text"].lower()
        z4 = flow.zug(sit, "Ich möchte meinen Termin absagen.")
        assert z4, "Neustart fehlt (fiel frueher ans LLM)"
        assert "wie ist ihr nachname" in z4["text"].lower()
    finally:
        verwalten.kal.find_patient_appointments = echt_find


def test_verwaltung_hinweis_passt_nicht_ehrliche_rueckfrage():
    """Hinweis (Dienstag) passt auf keinen Termin: ehrlich zeigen, was es
    gibt — 'Meinen Sie den?'; ein 'Ja' waehlt den einzigen Treffer, ein
    'Nein' fuehrt zur ehrlichen Notiz."""
    echt_find = verwalten.kal.find_patient_appointments
    verwalten.kal.find_patient_appointments = lambda t, c: dict(GEFUNDEN)
    try:
        sit = _sit()
        flow.zug(sit, "Ich muss meinen Termin am Dienstag absagen.")
        z = flow.zug(sit, "Martin Berger.")
        assert z and "meinen sie den" in z["text"].lower()
        assert gehirn.sammler(sit)["phase"] == "wahl"

        z2 = flow.zug(sit, "Ja, genau den.")
        assert z2 and "wirklich absagen" in z2["text"].lower()
    finally:
        verwalten.kal.find_patient_appointments = echt_find


def test_verwaltung_wahl_nein_fuehrt_zu_notiz():
    echt_find = verwalten.kal.find_patient_appointments
    verwalten.kal.find_patient_appointments = lambda t, c: dict(GEFUNDEN)
    try:
        sit = _sit()
        flow.zug(sit, "Ich muss meinen Termin am Dienstag absagen.")
        flow.zug(sit, "Martin Berger.")
        z = flow.zug(sit, "Nein, den meine ich nicht.")
        assert z and "notiz" in z["text"].lower() and "vorgelegt" in z["text"].lower()
        assert "Martin Berger" in (sit.get("praxisNotiz") or "")
    finally:
        verwalten.kal.find_patient_appointments = echt_find


GEFUNDEN_ZWEI = {
    "ok": True,
    "patient": {"id": "pat-1", "firstName": "Martin", "lastName": "Berger"},
    "appointments": [
        {
            "id": "apt-1", "iso": "2026-09-03T10:00", "date": "2026-09-03",
            "calendarId": "zex5bmv5jfIHWVW6zHbg", "doctorName": "Dr. Petsas",
            "motivId": "vm-1", "motivName": "01 Kontrolluntersuchung",
            "spoken": "am Donnerstag, den dritten September um zehn Uhr bei Dr. Petsas",
        },
        {
            "id": "apt-2", "iso": "2026-09-08T14:30", "date": "2026-09-08",
            "calendarId": "kal-niko", "doctorName": "Dr. Nikolaou",
            "motivId": "vm-7", "motivName": "PZR / Professionelle Zahnreinigung",
            "spoken": "am Dienstag, den achten September um vierzehn Uhr dreißig bei Dr. Nikolaou",
        },
    ],
}


def test_verwaltung_behandlung_grenzt_ein():
    """Chef: hilfsweise die BEHANDLUNG erfragen — 'Zahnreinigung' trifft
    den PZR-Termin, ohne dass der Anrufer die Liste durchgehen muss."""
    echt_find = verwalten.kal.find_patient_appointments
    verwalten.kal.find_patient_appointments = lambda t, c: dict(GEFUNDEN_ZWEI)
    try:
        sit = _sit()
        flow.zug(sit, "Ich möchte meinen Termin absagen.")
        z = flow.zug(sit, "Martin Berger.")
        assert z and "für welche behandlung" in z["text"].lower()
        assert gehirn.sammler(sit)["frage"] == "behandlung"

        z2 = flow.zug(sit, "Das war für die Zahnreinigung.")
        assert z2 and "wirklich absagen" in z2["text"].lower()
        assert sit.get("verwaltenTermin") == "apt-2"
    finally:
        verwalten.kal.find_patient_appointments = echt_find


def test_verwaltung_behandler_filtert_kalender():
    """Behandler im Einstiegssatz genannt: die Treffer werden auf seinen
    Kalender gefiltert (Chef: 'um nicht in allen kalendern zu suchen') —
    ohne Behandler-Vorabfrage (W-NACHNAME)."""
    echt_find = verwalten.kal.find_patient_appointments
    verwalten.kal.find_patient_appointments = lambda t, c: dict(GEFUNDEN_ZWEI)
    try:
        sit = _sit()
        z = flow.zug(sit, "Ich möchte meinen Termin bei Doktor Petsas absagen.")
        assert z and "wie ist ihr nachname" in z["text"].lower()
        z2 = flow.zug(sit, "Martin Berger.")
        assert z2 and "wirklich absagen" in z2["text"].lower()
        assert sit.get("verwaltenTermin") == "apt-1"  # nur der Petsas-Termin
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


def test_frisch_absage_nach_llm_storno_frage():
    """Live 02.09. Tzannis: nach Buchung fragte das LLM 'Soll ich stornieren?',
    Anrufer 'Yeah.' — Antwort 'Der Termin ist storniert' OHNE Tool. Jetzt
    cancel_appointment auf den frisch gebuchten Termin."""
    from bianca import verwalten
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "phase": "gebucht", "frage": "",
        "vorname": "Kiriakos", "nachname": "Tzannis",
        "slotIso": "2026-09-02T10:15:00+02:00",
        "arzt": {"typ": "genannt", "calendarId": "calPetsas", "calendarName": "Dr. Petsas"},
    })
    sit["booking"] = {"appointmentId": "YYFlonPPFQifsUK61UU0"}
    sit["lastBook"] = {
        "appointmentId": "YYFlonPPFQifsUK61UU0",
        "slotIso": "2026-09-02T10:15:00+02:00",
        "ok": True,
    }
    sit["messages"] = [
        {"role": "system", "content": "x"},
        {"role": "assistant", "content": "Der Termin heute um zehn Uhr fünfzehn ist fest eingetragen."},
        {"role": "user", "content": "Ah nee, ich schaff's schon anders."},
        {"role": "assistant", "content": "Verstehe. Soll ich den Termin dann für Sie stornieren?"},
    ]
    calls: list[str] = []
    echt = verwalten.kal.cancel_by_id

    def _cancel(tenant, ctx, aid):
        calls.append(aid)
        return {"ok": True, "cancelled": True, "appointmentId": aid,
                "spoken": "Der Termin ist abgesagt."}

    verwalten.kal.cancel_by_id = _cancel
    try:
        z = flow.zug(sit, "Yeah.")
    finally:
        verwalten.kal.cancel_by_id = echt
    assert calls == ["YYFlonPPFQifsUK61UU0"], calls
    assert z and ("abgesagt" in z["text"].lower() or "erledigt" in z["text"].lower())
    assert (z.get("book") or {}).get("cancelled") is True
    assert s["phase"] == "fertig"


def test_frisch_absage_wunsch_bestaetigt_ohne_namenssuche():
    """'Sagen Sie den Termin doch wieder ab' nach Buchung: Bestaetigungsfrage
    fuer den frischen Termin, kein Nachnamen-Suchen."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "phase": "gebucht",
        "vorname": "Kiriakos", "nachname": "Tzannis",
        "slotIso": "2026-09-02T10:15:00+02:00",
    })
    sit["booking"] = {"appointmentId": "aid-frisch"}
    z = flow.zug(sit, "Ach warten Sie — bitte sagen Sie den Termin doch wieder ab.")
    assert s["modus"] == "absagen"
    assert s["phase"] == "absage_bestaetigen"
    assert z and "wirklich absagen" in z["text"].lower()
    assert "nachname" not in z["text"].lower()


def test_erledigt_wache_bei_gebucht_fragt_nach():
    """LLM behauptet Storno bei phase=gebucht ohne Tool → Rueckfrage statt Luege."""
    from bianca import agent as agentmod
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "phase": "gebucht", "frage": ""})
    sit["booking"] = {"appointmentId": "aid-x"}
    sit["lastBook"] = {"appointmentId": "aid-x", "slotIso": "2026-09-02T10:15:00+02:00"}
    raus = agentmod._nachbessern(
        sit, "Der Termin ist storniert. Gibt es sonst noch etwas für Sie?",
        werkzeug_lief=False,
    )
    assert "storniert" not in raus.lower() or "wirklich" in raus.lower()
    assert "absagen" in raus.lower()
    assert s["frage"] == "frisch_absage_ok"


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
    echt_find = flow.kal.find_slots
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit()
        s = gehirn.sammler(sit)
        slot = _iso_in(30, 9, 30)
        s.update({"modus": "buchen", "warSchonMal": True,
                  "arzt": {"typ": "genannt", "calendarId": "zex5bmv5jfIHWVW6zHbg", "calendarName": "Dr. Petsas"},
                  "vorname": "Michael", "nachname": "Petsas", "buchstabiert": True,
                  "grund": "Kontrolluntersuchung", "motivId": "vm-kontrolle",
                  "motivName": "Kontrolluntersuchung", "wunsch": {},
                  "telefonAkte": True, "phase": "angebot", "frage": "slotwahl"})
        sit["slotVorrat"] = [slot]
        # W-MOTIV-FENSTER: Vorrat gilt nur mit passendem Rahmen-Marker; der
        # neue Wunsch aendert das Startdatum, also laedt der Zug nach — der
        # Mock liefert denselben Slot, die Wiederhol-Wache muss greifen.
        from bianca import hintergrund as hg
        sit["vorratFuer"] = hg.vorrat_schluessel(sit)
        flow.kal.find_slots = lambda *a, **k: {"ok": True, "slots": [slot]}
        sit["offered"] = [{"iso": slot, "spoken": "in vier Wochen um neun Uhr dreißig"}]
        z = flow.zug(sit, "Ginge es auch nächste Woche?")
        assert z and "es bleibt bei" in z["text"], z
        assert [o["iso"] for o in sit["offered"]] == [slot]
    finally:
        flow.hintergrund.anstossen = echt_anstossen
        flow.kal.find_slots = echt_find


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
              "grund": "akute Beschwerden/Notfall", "motivId": "vm-akut",
              "motivName": "Schmerzbehandlung", "wunsch": {},
              "telefonAkte": True})
    dicht = [_iso_in(30, 12, 15), _iso_in(30, 12, 45), _iso_in(30, 13, 15)]
    sit["slotVorrat"] = list(dicht)
    # W-MOTIV-FENSTER: der Vorrat zaehlt nur mit passendem Rahmen-Marker.
    from bianca import hintergrund as hg
    sit["vorratFuer"] = hg.vorrat_schluessel(sit)
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


def test_buchstabieren_stt_cluster_und_wortanker():
    """STT klebte live (29.08.2026) "F-E-L-D-K-A-M-P" zu "F-E-LD-Kamp" —
    deute lieferte None, buchstabiert blieb False, die Frage loopte endlos."""
    # Wort-Anker: das mitgesprochene "Feldkamp" bestätigt die Anfangsbuchstaben.
    d = buchstaben.deute("Feldkamp, also F-E-LD-Kamp.")
    assert d and d["name"] == "Feldkamp" and d["sicher"]
    # Ohne Namenswort: Cluster-Split + Suffix-Fuge setzen die Kette zusammen.
    d2 = buchstaben.deute("F-E-LD-Kamp")
    assert d2 and d2["name"] == "Feldkamp"
    # Bestätigendes Wort NACH der Kette darf nicht doppeln.
    d3 = buchstaben.deute("M-E-I-E-R, Meier")
    assert d3 and d3["name"] == "Meier"
    # Bewährte Formen bleiben unverändert.
    d4 = buchstaben.deute("Also der Nachname ist Panzer. P-A-N-Z-E-R. Der Vorname ist Paul")
    assert d4 and d4["name"] == "Panzer"


def test_buchstabieren_cluster_beendet_den_loop_im_sammler():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["frage"] = "buchstabieren"
    s["nachname"] = "Feldkamp"
    gehirn.einsammeln(sit, "Feldkamp, also F-E-LD-Kamp.")
    assert s["nachname"] == "Feldkamp" and s["buchstabiert"]


def test_buchstabieren_verhoerer_haelt_gesagten_namen():
    """Live 29.08.2026: "W wie Wilhelm" kam als "B. Wilhelm" an — die
    unsichere Kette "Grunebwald" darf den gesagten Namen nicht verdraengen."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["frage"] = "buchstabieren"
    s["nachname"] = "Grunewald"
    gehirn.einsammeln(sit, "Ich buchstabiere G. wie Gustav, R. wie Richard, "
                           "U wie Ulrich, N. wie Nordpol, E. wie Emil, "
                           "B. Wilhelm, A. wie Anton, L. wie Ludwig, D. wie Dora.")
    assert s["nachname"] == "Grunewald" and s["buchstabiert"]


def test_buchstabieren_kette_verliert_buchstaben_gegen_gesagten_namen():
    """Live 29.08.2026 (s09): Kette kam als "Stinfurt" an (E verschluckt),
    der Anrufer hatte "Steinfurt" gesagt — der laengere gesagte Name gewinnt."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["frage"] = "buchstabieren"
    s["nachname"] = "Steinfurt"
    gehirn.einsammeln(sit, "Ich buchstabiere SW Samuel, T. wie Theodor, Ew Emil, "
                           "Ew Ida, N. wie Nordpol, F. wie Friedrich, Uwi Ulrich, "
                           "R. wie Richard, T. wie Theodor.")
    assert s["nachname"] == "Steinfurt" and s["buchstabiert"]


def test_buchstabieren_echte_korrektur_bleibt():
    """Weit entfernte Buchstabierung KORRIGIERT weiterhin (MATTA-VATTA-Regel):
    wer einen anderen Namen buchstabiert, meint ihn auch."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["frage"] = "buchstabieren"
    s["nachname"] = "Pidoq"
    gehirn.einsammeln(sit, "M wie Martha, A wie Anton, T wie Theodor, "
                           "T wie Theodor, A wie Anton.")
    assert s["nachname"] == "Matta"


def test_buchstabieren_kurzkette_als_wort_gehoert():
    """Live 29.08.2026: "Q-U-A-N-D-T" kam als "Quant also Quandt" an —
    das Token nahe am gespeicherten Namen ist die Praezisierung."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["frage"] = "buchstabieren"
    s["nachname"] = "Quand"
    gehirn.einsammeln(sit, "Quant also Quandt.")
    assert s["nachname"] == "Quandt" and s["buchstabiert"]


def test_verschoben_worden_ist_kein_verschiebe_wunsch():
    """Beschwerde "zweimal von Ihnen verschoben worden" darf die laufende
    Buchung nicht in den Verwaltungs-Modus kippen (Batch 29.08.2026)."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["frage"] = "grund"
    gehirn.einsammeln(sit, "Mein letzter Termin ist übrigens zweimal von "
                           "Ihnen verschoben worden.")
    assert s["modus"] == "buchen"
    # Ein echter Wunsch bewaffnet weiterhin:
    sit2 = _sit()
    s2 = gehirn.sammler(sit2)
    s2["modus"] = ""
    gehirn.einsammeln(sit2, "Ich möchte meinen Termin gern verschieben.")
    assert s2["modus"] == "verschieben"
    # Auch mit Passiv-Vorgeschichte im selben Satz:
    sit3 = _sit()
    s3 = gehirn.sammler(sit3)
    s3["modus"] = ""
    gehirn.einsammeln(sit3, "Der Termin wurde schon zweimal verschoben, "
                            "aber jetzt muss ich ihn selbst verschieben.")
    assert s3["modus"] == "verschieben"


def test_hergezogen_ist_kein_name():
    """"Nein, noch nie, ich bin gerade erst hergezogen" wurde live
    (29.08.2026) als Name "Gerade Hergezogen" geerntet."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["frage"] = "schonmal"
    gehirn.einsammeln(sit, "Nein, noch nie, ich bin gerade erst hergezogen.")
    assert not s["vorname"] and not s["nachname"]


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


def test_besuchsgrund_ueberweiser_und_invisalign():
    """Ueberweiser-Wissen (Chef 29.08.2026): Grüger/Lange/Schlaflabor sind
    Narval-Ueberweiser -> SLM Besprechung; Invisalign/schiefe Zähne -> KFO.
    'ich warte schon lange' ist KEINE Ueberweisung."""
    from bianca import besuchsgrund
    tenant = _sit()["tenant"]
    kern, vm = besuchsgrund.deute(tenant, "Ich bin von Doktor Grüger überwiesen worden")
    assert kern == "Schiene/Schnarchen"
    assert vm and vm["name"] == "SLM Besprechung"
    kern, vm = besuchsgrund.deute(tenant, "Das Schlaflabor hat mich zu Ihnen überwiesen")
    assert kern == "Schiene/Schnarchen"
    kern, vm = besuchsgrund.deute(tenant, "Dr. Lange hat mich geschickt")
    assert kern == "Schiene/Schnarchen"
    assert vm and vm["name"] == "SLM Besprechung"
    # "lange" ohne Titel ist keine Ueberweisung:
    kern, _ = besuchsgrund.deute(tenant, "Ich warte schon lange auf einen Termin")
    assert kern != "Schiene/Schnarchen"
    # Invisalign ist KFO, auch wenn "Schienen" im Satz steht:
    kern, vm = besuchsgrund.deute(tenant, "Ich hätte gern eine Invisalign-Beratung")
    assert kern == "Invisalign-Beratung"
    assert vm and vm["name"] == "KFO Besprechung"
    kern, vm = besuchsgrund.deute(tenant, "Meine Invisalign-Schienen drücken ein bisschen")
    assert kern == "Invisalign-Beratung"
    kern, vm = besuchsgrund.deute(tenant, "Ich will meine schiefen Zähne gerade machen lassen")
    assert kern == "Zahnspange/KFO"
    assert vm and vm["name"] == "KFO Besprechung"
    # Schlafschiene bleibt SLM (Bestand):
    kern, vm = besuchsgrund.deute(tenant, "Ich schnarche und brauche eine Schlafschiene")
    assert kern == "Schiene/Schnarchen"
    assert vm and vm["name"] == "SLM Besprechung"


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


def test_yeah_zaehlt_als_ja():
    """Live 01.09. Rebrovic: 'Yeah.' auf die Bestätigung wurde nicht erkannt."""
    assert gehirn.ist_ja("Yeah.")
    assert gehirn.ist_ja("Yeah")
    assert gehirn.ist_ja("yea")
    assert gehirn.ist_ja("Yes.")


def test_wunsch_gleich_heute_noch_ohne_nachfrage():
    """Live 01.09. Rebrovic: 'Am liebsten gleich' → nochmal vormittags/nachmittags."""
    from datetime import datetime
    from kern.slots import TZ
    heute = datetime.now(TZ).date().isoformat()

    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "wunsch", "warSchonMal": True})
    neu = gehirn.einsammeln(sit, "Am liebsten gleich.")
    assert "wunsch" in neu
    assert s["wunsch"] and s["wunsch"].get("date") == heute

    sit2 = _sit()
    s2 = gehirn.sammler(sit2)
    s2.update({"modus": "buchen", "frage": "wunsch"})
    neu2 = gehirn.einsammeln(sit2, "Am besten heute noch, weil ich Schmerzen habe.")
    assert "wunsch" in neu2
    assert s2["wunsch"].get("date") == heute

    # "ganz gleich" bleibt egal / keine Zeit
    sit3 = _sit()
    s3 = gehirn.sammler(sit3)
    s3.update({"modus": "buchen", "frage": "wunsch"})
    gehirn.einsammeln(sit3, "Das ist mir ganz gleich.")
    assert s3["wunsch"] == {}


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
    Ziffern-/Buchstabier-Diktate brauchen Diktat-Geduld (W-STT-SCHWANZ:
    1500 ms — Gruppen-Pausen nie als Zugende), sonst 500."""
    assert gehirn.stille_ms({"frage": "schonmal"}) == 350
    assert gehirn.stille_ms({"frage": "arzt"}) == 350
    assert gehirn.stille_ms({"frage": "telefon_check"}) == 350
    assert gehirn.stille_ms({"frage": "pzr"}) == 350
    assert gehirn.stille_ms({"frage": "telefon"}) == 1500
    assert gehirn.stille_ms({"frage": "buchstabieren"}) == 1500
    # Die Verwaltungs-Nachnamen-Frage laedt zum Buchstabieren ein (31.08.):
    assert gehirn.stille_ms({"frage": "nachname"}) == 1500
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
    """Readback bleibt Dreisatz: Vorsatz und Schlussfrage sind eigene,
    warmbare Saetze (feste_saetze) — der Blocking-Pfad (_sprech_blob)
    pinned sie aus dem Cache, der Ziffern-Satz wird verifiziert dazwischen.
    W-TTS-STOCK: Mid-Stream-Parallelisierung ist aus; die Form bleibt."""
    t = gehirn.readback_text("01776004600")
    saetze = re.split(r"(?<=[.!?]) +(?=[A-ZÄÖÜ])", t)
    assert saetze[0] == "Ich wiederhole die Nummer."
    assert saetze[-1] == "Stimmt das so?"
    assert saetze[1].startswith("Null eins sieben sieben")
    fest = gehirn.feste_saetze()
    assert saetze[0] in fest and saetze[-1] in fest


# --- W-ANRUFER-CHECK (31.08.2026): erkannten Anrufer vorlesen statt fragen --

def _sit_mit_anrufer() -> dict:
    """Sitzung, in der kern/agentprofil den Kartei-Patienten zur
    Anrufernummer hinterlegt hat (SIP mit uebermittelter Nummer)."""
    sit = _sit()
    sit["anrufer"] = {
        "vorname": "Julia", "nachname": "Berger", "patientId": "pat-7",
        "geschlecht": "female", "telefon": "+4915253904756",
    }
    return sit


def test_anrufer_check_buchung_ja_uebernimmt_name_und_nummer():
    """Chef 31.08.2026: 'den namen und die telefonnummer bei der buchung …
    vorzulesen als kontrolle anstatt das nochmal zu erfragen.' Ein Ja
    uebernimmt BEIDES — danach fragt der Fluss NIE wieder nach Name,
    Buchstabierung oder Handynummer."""
    from bianca import agent as bianca_agent

    echt_anstossen = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit_mit_anrufer()
        z1 = flow.zug(sit, "Guten Tag, ich hätte gern einen Termin.")
        assert z1 and "Julia Berger" in z1["text"]
        assert "null eins fünf zwei" in z1["text"]  # Nummer wird VORGELESEN
        assert re.search(bianca_agent._FRAGE_KERN["anrufer_check"], z1["text"], re.I)
        s = gehirn.sammler(sit)
        assert s["frage"] == "anrufer_check"
        assert gehirn.stille_ms(s) == 350  # Ja/Nein-Frage: kurze Ruhe reicht

        z2 = flow.zug(sit, "Ja, genau.")
        s = gehirn.sammler(sit)
        assert s["anruferCheck"] == "ja"
        assert s["warSchonMal"] is True  # steht in der Kartei => Bestand
        assert s["vorname"] == "Julia" and s["nachname"] == "Berger"
        assert s["patientId"] == "pat-7" and s["bekannt"] and s["buchstabiert"]
        assert s["telefonOk"] and s["telefon"] == "015253904756"
        assert s["geschlecht"] == "f" and s["geschlechtQuelle"] == "akte"
        assert z2 and "Danke, Julia Berger" in z2["text"]
        assert s["frage"] == "arzt"  # weiter im Bestand-Fluss
        # Name/Buchstabieren/Telefon kommen NIE wieder:
        s["arzt"] = {"typ": "genannt", "calendarId": "cal-1", "calendarName": "Dr. Petsas"}
        s["grund"] = "Kontrolle"
        s["wunsch"] = {}
        fid, _ = gehirn.naechste_frage(sit)
        assert fid not in {"name", "nachname", "vorname", "buchstabieren",
                           "telefon", "telefon_check", "anrufer_check"}
    finally:
        flow.hintergrund.anstossen = echt_anstossen


def test_anrufer_check_nein_fragt_klassisch():
    """Bestaetigt der Anrufer den Kartei-Treffer NICHT, wird er verworfen —
    der Fluss fragt klassisch (schonmal/Name/Nummer) und bietet den
    Treffer nie wieder an."""
    echt_anstossen = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit_mit_anrufer()
        flow.zug(sit, "Ich möchte einen Termin vereinbaren.")
        z2 = flow.zug(sit, "Nein, das bin ich nicht.")
        s = gehirn.sammler(sit)
        assert s["anruferCheck"] == "nein"
        assert not s["nachname"] and not s["telefonOk"] and not s["patientId"]
        assert z2 and "frisch auf" in z2["text"]
        assert s["frage"] == "schonmal"
        fid, _ = gehirn.naechste_frage(sit)
        assert fid == "schonmal"  # der verworfene Treffer kommt nie wieder
    finally:
        flow.hintergrund.anstossen = echt_anstossen


def test_anrufer_check_nicht_bei_neupatient_oder_drittem():
    """Kein Vorlesen, wenn sich der Anrufer als Neupatient bekannt hat
    (Kartei-Treffer ist dann wohl ein Angehoeriger am selben Anschluss)
    oder der Termin fuer einen Dritten ist ('fuer meine Tochter')."""
    sit = _sit_mit_anrufer()
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["warSchonMal"] = False
    fid, _ = gehirn.naechste_frage(sit)
    assert fid != "anrufer_check"

    sit2 = _sit_mit_anrufer()
    s2 = gehirn.sammler(sit2)
    s2["modus"] = "buchen"
    s2["fuerWen"] = "tochter"
    fid2, _ = gehirn.naechste_frage(sit2)
    assert fid2 != "anrufer_check"

    # Ohne Anrufer-Daten (Dock, unterdrueckte Nummer): alles wie immer.
    sit3 = _sit()
    gehirn.sammler(sit3)["modus"] = "buchen"
    fid3, _ = gehirn.naechste_frage(sit3)
    assert fid3 == "schonmal"


def test_absage_mit_erkanntem_anrufer_sucht_direkt():
    """Beim Absagen wird der erkannte Anrufer vorgelesen statt der
    Nachnamen-Frage; ein Ja sucht SOFORT mit Kartei-Name, patientId und
    Anrufernummer."""
    echt_find = verwalten.kal.find_patient_appointments
    echt_anstossen = verwalten.hintergrund.anstossen
    gesucht: list[dict] = []

    def _find(t, c):
        gesucht.append(dict(c))
        return dict(GEFUNDEN)

    verwalten.kal.find_patient_appointments = _find
    verwalten.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit_mit_anrufer()
        z1 = flow.zug(sit, "Guten Tag, ich muss leider meinen Termin absagen.")
        assert z1 and "Julia Berger" in z1["text"]
        assert "nachname" not in z1["text"].lower()  # NICHT nochmal erfragen
        assert gehirn.sammler(sit)["frage"] == "anrufer_check"

        z2 = flow.zug(sit, "Ja.")
        assert z2 and "wirklich absagen" in z2["text"].lower(), z2
        assert "Frau Berger" in z2["text"]  # Kartei-Geschlecht traegt die Anrede
        assert gesucht[-1].get("lastName") == "Berger"
        assert gesucht[-1].get("patientId") == "pat-7"
        assert gesucht[-1].get("phone") == "015253904756"
    finally:
        verwalten.kal.find_patient_appointments = echt_find
        verwalten.hintergrund.anstossen = echt_anstossen


def test_absage_anrufer_check_nein_fragt_nachnamen():
    """Nein auf den vorgelesenen Treffer: die bewaehrte Nachnamen-Frage
    (mit Buchstabier-Einladung) kommt wie vor W-ANRUFER-CHECK."""
    echt_anstossen = verwalten.hintergrund.anstossen
    verwalten.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit_mit_anrufer()
        flow.zug(sit, "Ich möchte meinen Termin absagen.")
        z2 = flow.zug(sit, "Nein.")
        assert z2 and "wie ist ihr nachname" in z2["text"].lower()
        s = gehirn.sammler(sit)
        assert s["frage"] == "nachname" and s["anruferCheck"] == "nein"
    finally:
        verwalten.hintergrund.anstossen = echt_anstossen


def test_auskunft_mit_erkanntem_anrufer():
    """Auch die Termin-Auskunft liest den erkannten Anrufer vor, statt den
    Nachnamen zu erfragen."""
    echt_find = verwalten.kal.find_patient_appointments
    echt_anstossen = verwalten.hintergrund.anstossen
    verwalten.kal.find_patient_appointments = lambda t, c: dict(GEFUNDEN)
    verwalten.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit_mit_anrufer()
        z1 = flow.zug(sit, "Ich weiß nicht mehr, wann mein Termin ist.")
        assert z1 and "Julia Berger" in z1["text"]
        assert gehirn.sammler(sit)["frage"] == "anrufer_check"
        z2 = flow.zug(sit, "Ja, richtig.")
        assert z2 and "dritten September" in z2["text"]  # Termin wird vorgelesen
    finally:
        verwalten.kal.find_patient_appointments = echt_find
        verwalten.hintergrund.anstossen = echt_anstossen


def test_anrufer_check_eskalation_verwirft_treffer():
    """Zweimal keine klare Antwort auf die Identitaets-Kontrolle: NICHTS
    uebernehmen (Sicherheit vor Tempo) — weiter mit der schonmal-Frage."""
    echt_anstossen = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        sit = _sit_mit_anrufer()
        flow.zug(sit, "Ich hätte gern einen Termin.")
        z2 = flow.zug(sit, "Äh, Moment, der Hund bellt gerade.")
        # Erster Leerlauf: deterministische Kurz-Nachfrage, nie ans LLM.
        assert z2 and "richtig erkannt" in z2["text"].lower()
        z3 = flow.zug(sit, "Der Hund bellt immer noch.")
        s = gehirn.sammler(sit)
        assert s["anruferCheck"] == "nein"
        assert not s["nachname"] and not s["telefonOk"]
        assert z3 and "schon einmal bei uns" in z3["text"]
    finally:
        flow.hintergrund.anstossen = echt_anstossen


# --- W-BOOK-RETRY 01.09.2026: slotTaken-Deckel -----------------------------

def _buch_sit(slot_iso: str) -> dict:
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "phase": "bestaetigen", "frage": "bestaetigung",
        "warSchonMal": False, "grund": "akute Beschwerden/Notfall",
        "motivName": "Akute Beschwerden / Notfall", "wunsch": {},
        "vorname": "Schacklin", "nachname": "Rebrovic", "buchstabiert": True,
        "telefon": "016090356870", "telefonOk": True,
        "slotIso": slot_iso,
        "arzt": {"typ": "genannt", "calendarId": "cal-thaler", "calendarName": "Thaler"},
    })
    sit["offered"] = [{"iso": slot_iso, "spoken": "heute um elf Uhr dreißig"}]
    sit["angebotKalender"] = {"calendarId": "cal-thaler", "calendarName": "Thaler"}
    sit["slotVorrat"] = [
        slot_iso,
        "2026-09-03T11:00:00+02:00",
        "2026-09-03T14:00:00+02:00",
        "2026-09-04T09:00:00+02:00",
    ]
    return sit


def test_book_retry_sperrt_iso_und_deckelt_nach_zwei_fails():
    """Live 01.09. Rebrovic: nach Ja kam 'gerade weg' ×5. Max. 2 Fails, dann
    Notiz — gescheiterte ISO nie wieder anbieten."""
    iso1 = "2026-09-03T10:00:00+02:00"
    iso2 = "2026-09-03T11:00:00+02:00"
    sit = _buch_sit(iso1)
    notizen: list = []
    angebote: list = []

    def _fail_book(tenant, ctx, slot_iso=""):
        return {
            "ok": False, "slotTaken": True, "slotIso": slot_iso,
            "spoken": "Der Termin ist gerade weg.",
            "slots": [{"iso": iso2, "spoken": "heute um elf"}],
        }

    echt_book = flow.kal.book_slot
    echt_notiz = flow.verwalten._notiz_schreiben
    echt_find = flow.kal.find_slots
    flow.kal.book_slot = _fail_book
    flow.verwalten._notiz_schreiben = (
        lambda sit, **kw: notizen.append(kw) or None
    )
    # _angebot soll aus dem lokalen Vorrat schöpfen, nicht die CF anrufen.
    flow.kal.find_slots = lambda *a, **k: {"ok": False}

    try:
        r1 = flow._buchen(sit)
        assert sit["bookFails"] == 1
        assert sit["buchIntent"] is True
        assert iso1 in sit["slotGesperrt"]
        assert iso1[:16] not in {str(v)[:16] for v in sit.get("slotVorrat") or []}
        assert r1 and "gerade weg" in r1["text"].lower()
        assert gehirn.sammler(sit)["phase"] == "angebot"
        angebote.append(r1["text"])

        # Zweite Wahl mit Intent: direkt buchen, KEIN Confirm-Readback.
        s = gehirn.sammler(sit)
        s["slotIso"] = iso2
        # offered muss die Alternativen tragen
        sit["offered"] = [{"iso": iso2, "spoken": "heute um elf"}]
        r_pick = flow.zug(sit, "Dann nehme ich elf Uhr.")
        # zug mit buchIntent + klarer Wahl -> _buchen -> zweiter Fail -> Notiz
        assert sit["bookFails"] == 2
        assert r_pick and "notiz" in r_pick["text"].lower()
        assert "praxis meldet sich" in r_pick["text"].lower()
        assert gehirn.sammler(sit)["phase"] == "fertig"
        assert notizen, "Rueckruf-Notiz muss geschrieben sein"
        assert "Dann halte ich fest" not in (r_pick.get("text") or "")
    finally:
        flow.kal.book_slot = echt_book
        flow.verwalten._notiz_schreiben = echt_notiz
        flow.kal.find_slots = echt_find


def test_book_retry_nach_ja_fail_bucht_alternativ_ohne_zweites_confirm():
    """Nach erstem Ja+Fail: gewählte Alternative wird ohne 'Soll ich eintragen?' gebucht."""
    iso1 = "2026-09-03T10:00:00+02:00"
    iso2 = "2026-09-03T11:00:00+02:00"
    sit = _buch_sit(iso1)
    sit["buchIntent"] = True
    sit["bookFails"] = 1
    sit["slotGesperrt"] = [iso1]
    sit["offered"] = [
        {"iso": iso2, "spoken": "heute um elf Uhr"},
        {"iso": "2026-09-04T09:00:00+02:00", "spoken": "übermorgen um neun"},
    ]
    gehirn.sammler(sit)["phase"] = "angebot"
    gehirn.sammler(sit)["frage"] = "slotwahl"
    gehirn.sammler(sit)["slotIso"] = ""

    gebucht: list = []

    def _ok_book(tenant, ctx, slot_iso=""):
        gebucht.append(slot_iso)
        return {
            "ok": True, "booked": True, "slotIso": slot_iso,
            "appointmentId": "ok1",
            "spoken": f"Der Termin ist fest eingetragen.",
        }

    echt = flow.kal.book_slot
    echt_note = flow.kal.note_appointment
    flow.kal.book_slot = _ok_book
    flow.kal.note_appointment = lambda *a, **k: {"ok": True}
    try:
        r = flow.zug(sit, "Elf Uhr bitte.")
        assert gebucht and iso2 in gebucht[0]
        assert r and "fest eingetragen" in r["text"]
        assert "Soll ich" not in r["text"] and "halte ich fest" not in r["text"]
        assert not sit.get("buchIntent")
    finally:
        flow.kal.book_slot = echt
        flow.kal.note_appointment = echt_note
