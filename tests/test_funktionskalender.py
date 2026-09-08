"""Funktionskalender (Thaler): Prophylaxe ist kein Behandler.

Eva Thaler ist ein Zahn-Klon von MedDent. Unterschied nur im Roster:
eine Zahnaerztin + Kalender 'Prophylaxe' (Ort fuer Zahnreinigung).
Beim Zahnarzt nur Besprechung/Kontrolle — Füllung wird umgebogen.
Schmerz bleibt Notfall. MedDent ohne Funktionskalender bleibt gleich.
"""

from __future__ import annotations

from bianca import arzt as arztmod
from bianca import flow, gehirn
from kern import tenants as kern_tenants
from kern.tenants import laden


EVA = "cal-eva"
Z1 = "cal-zi1"
Z2 = "cal-zi2"
Z3 = "cal-zi3"
Z4 = "cal-zi4"
PROPHY = Z3

THALER_KAT = [
    {"id": "akut", "name": "KCH Akute Beschwerden / Notfall",
     "nameForPatient": "Akute Beschwerden", "allowOnlineBooking": True,
     "calendarIds": [Z1]},
    {"id": "bespr", "name": "ZE Besprechung",
     "nameForPatient": "Zahnersatz-Besprechung", "allowOnlineBooking": True,
     "calendarIds": [Z4]},
    {"id": "recall", "name": "Recall Check-up",
     "nameForPatient": "Kontrolle", "allowOnlineBooking": True,
     "calendarIds": [Z4]},
    {"id": "fuell", "name": "KCH Füllung klein",
     "nameForPatient": "Füllung", "allowOnlineBooking": True,
     "calendarIds": [Z4]},
    {"id": "pzr", "name": "PRO professionelle Zahnreinigung",
     "nameForPatient": "Zahnreinigung", "allowOnlineBooking": True,
     "calendarIds": [Z3, Z2]},
]


def _thaler(**extra):
    t = {
        "clientId": "thaler-test",
        "locationId": "loc",
        "praxisName": "Zahnarztpraxis Eva Thaler",
        "defaultCalendarId": EVA,
        "zimmerMap": {"pzr": [3, 2], "akut": [1], "behandlung": [4]},
        "calendars": [
            {"id": EVA, "name": "Dr. Eva Thaler"},
            {"id": Z1, "name": "Zimmer 1"},
            {"id": Z2, "name": "Zimmer 2"},
            {"id": Z3, "name": "Zimmer 3 Prophylaxe"},
            {"id": Z4, "name": "Zimmer 4"},
        ],
        "visitMotives": list(THALER_KAT),
    }
    t.update(extra)
    return t


def _sit(tenant=None):
    t = tenant or _thaler()
    return {
        "tenant": t,
        "messages": [{"role": "system", "content": "x"}],
        "motivKatalog": list(t.get("visitMotives") or []),
    }


def _ohne_hintergrund(fn):
    echt = flow.hintergrund.anstossen
    flow.hintergrund.anstossen = lambda sit: None
    try:
        return fn()
    finally:
        flow.hintergrund.anstossen = echt


# --- Roster ----------------------------------------------------------------

def test_prophylaxe_ist_funktionskalender():
    assert kern_tenants.ist_funktionskalender("Prophylaxe")
    assert kern_tenants.ist_funktionskalender({"name": "Zimmer 3 Prophylaxe", "id": Z3})
    assert kern_tenants.zimmer_nr("Irem (Zi 4)") == 4
    assert kern_tenants.zimmer_nr("Leonita (Zi2)") == 2
    assert not kern_tenants.ist_funktionskalender("Dr. Eva Thaler")
    assert not kern_tenants.ist_funktionskalender("Dr. Petsas")


def test_behandler_reihe_ohne_prophylaxe():
    namen = [c.get("name") for c in kern_tenants.behandler_reihe(_thaler())]
    assert namen == ["Dr. Eva Thaler"], namen


def test_meddent_reihe_unveraendert():
    t = laden("meddent")
    namen = [c.get("name") for c in kern_tenants.behandler_reihe(t)]
    assert namen == ["Dr. Petsas", "Dr. Patrikis", "Dr. Nikolaou"], namen
    assert kern_tenants.funktionskalender(t) is None


def test_default_kalender_ueberspringt_prophylaxe():
    t = _thaler(defaultCalendarId=PROPHY)
    d = kern_tenants.default_kalender(t)
    assert d and d["id"] == EVA


def test_arztwahl_nennt_prophylaxe_nicht():
    frage = gehirn.arztwahl_frage(_thaler())
    assert "Prophylaxe" not in frage
    assert "Thaler" in frage or "Behandler" in frage


def test_neupatient_fragt_thaler_oder_prophylaxe():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": False})
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "arzt", (fid, frage)
    assert "Frau Thaler" in frage
    assert "Prophylaxe" in frage
    assert "Behandler" not in frage


def test_bestand_fragt_nicht_letzten_behandler():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": True})
    sit["anruferKartei"] = {"calendarId": EVA, "calendarName": "Dr. Eva Thaler"}
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "arzt", (fid, frage)
    assert "Frau Thaler" in frage and "Prophylaxe" in frage
    assert "zuletzt" not in frage.lower()
    assert "Behandler" not in frage


def test_deute_prophylaxe_ist_kein_arzt():
    assert arztmod.deute("Ich möchte zur Prophylaxe.", _thaler()) is None
    hit = arztmod.deute("Zu Frau Thaler bitte.", _thaler())
    assert hit and hit["typ"] == "genannt" and hit["calendarId"] == EVA


def test_deute_eva_kahler_ist_thaler():
    """Live 08.09. Rebrovic: STT „Eva Kahler“ / „Frau Parler“."""
    for satz in ("Eva Kahler", "Frau Parler", "Zu Eva Thaler"):
        hit = arztmod.deute(satz, _thaler())
        assert hit and hit["typ"] == "genannt" and hit["calendarId"] == EVA, satz


def test_behandler_alle_ohne_prophylaxe():
    from bianca.agent import _behandler_alle
    zeile = _behandler_alle(_thaler())
    assert "Prophylaxe" not in zeile
    assert "Thaler" in zeile


# --- Routing ----------------------------------------------------------------

def test_zahnreinigung_landet_auf_prophylaxe():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "warSchonMal": False,
        "arzt": {"typ": "default", "calendarId": EVA, "calendarName": "Dr. Eva Thaler"},
        "grund": "Zahnreinigung", "motivId": "pzr",
        "motivName": "PRO professionelle Zahnreinigung",
        "grundWortlaut": "Zahnreinigung",
    })
    gehirn.kalender_zu_grund(sit)
    assert s["arzt"]["calendarId"] == Z3
    assert s["arzt"]["calendarName"] == "Prophylaxe"
    assert s["arzt"]["raeume"] == [Z3, Z2]


def test_kontrolle_bleibt_bei_eva():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "arzt": {"typ": "letzter", "calendarId": Z3, "calendarName": "Prophylaxe"},
        "grund": "Kontrolle", "motivId": "recall",
        "motivName": "Recall Check-up",
    })
    gehirn.kalender_zu_grund(sit)
    assert s["arzt"]["calendarId"] == Z4
    assert s["arzt"]["calendarName"] == "Dr. Eva Thaler"
    assert s["arzt"]["raeume"] == [Z4]


def test_fuellung_wird_besprechung():
    """Thaler mit Zimmer-Karte: Füllung bleibt Füllung und geht in Zimmer 4."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "arzt": {"typ": "default", "calendarId": EVA, "calendarName": "Dr. Eva Thaler"},
        "grund": "Füllung", "motivId": "fuell",
        "motivName": "KCH Füllung klein",
        "grundWortlaut": "Ich brauche eine Füllung",
    })
    vm = gehirn.motiv_fuer_kalender(sit, Z4)
    assert vm and vm["id"] == "fuell", vm
    gehirn.kalender_zu_grund(sit)
    assert s["arzt"]["calendarId"] == Z4


def test_schmerz_bleibt_notfall():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "arzt": {"typ": "default", "calendarId": EVA, "calendarName": "Dr. Eva Thaler"},
        "grund": "akute Beschwerden", "motivId": "akut",
        "motivName": "KCH Akute Beschwerden / Notfall",
        "grundWortlaut": "Ich habe starke Zahnschmerzen",
    })
    vm = gehirn.motiv_fuer_kalender(sit, Z1)
    assert vm and vm["id"] == "akut", vm
    gehirn.kalender_zu_grund(sit)
    assert s["arzt"]["calendarId"] == Z1
    assert s["arzt"]["raeume"] == [Z1]


def test_meddent_fuellung_wird_nicht_umgebogen():
    t = laden("meddent")
    sit = _sit(t)
    sit["motivKatalog"] = list(t.get("visitMotives") or [])
    s = gehirn.sammler(sit)
    s.update({
        "grund": "Füllung", "motivId": "fuell-fake",
        "motivName": "KCH Füllung klein",
        "grundWortlaut": "Füllung",
    })
    vm = {"id": "fuell-fake", "name": "KCH Füllung klein", "nameForPatient": "Füllung"}
    out = gehirn._besprechung_oder(sit, vm, "")
    assert out and out["id"] == "fuell-fake"


def test_arzt_check_sagt_zur_prophylaxe():
    sit = _sit()
    sit["anruferKartei"] = {"calendarId": PROPHY, "calendarName": "Prophylaxe"}
    frage = gehirn.arzt_check_frage(sit)
    assert "zur Prophylaxe" in frage
    assert "Doktor" not in frage


def test_arzt_check_ja_bindet_eva_nicht_prophylaxe():
    def lauf():
        sit = _sit()
        s = gehirn.sammler(sit)
        s.update({
            "modus": "buchen", "warSchonMal": True, "bekannt": True,
            "anruferCheck": "ja", "frage": "arzt_check",
            "vorname": "Anna", "nachname": "Berger",
            "buchstabiert": True, "telefonOk": True,
        })
        sit["anruferKartei"] = {
            "calendarId": PROPHY, "calendarName": "Prophylaxe",
        }
        flow.zug(sit, "Ja, ist richtig.")
        assert (s.get("arzt") or {}).get("calendarId") == EVA, s.get("arzt")
    _ohne_hintergrund(lauf)


def test_readback_bei_der_prophylaxe():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "arzt": {"typ": "funktion", "calendarId": PROPHY, "calendarName": "Prophylaxe"},
        "motivName": "PRO professionelle Zahnreinigung",
        "grund": "Zahnreinigung",
        "slotIso": "2026-09-10T09:00:00+02:00",
        "vorname": "Anna", "nachname": "Berger", "geschlecht": "f",
    })
    text = flow._readback(sit)["text"]
    assert "bei der Prophylaxe" in text
    assert "Doktor Prophylaxe" not in text
    assert "bei Prophylaxe" not in text.replace("bei der Prophylaxe", "")


def test_einsammeln_zahnreinigung_routet_kalender():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen", "warSchonMal": False,
        "arzt": {"typ": "default", "calendarId": EVA, "calendarName": "Dr. Eva Thaler"},
    })
    gehirn.einsammeln(sit, "Ich brauche eine Zahnreinigung.")
    assert s["arzt"]["calendarId"] == Z3
    assert s["arzt"].get("raeume") == [Z3, Z2]
    assert "zahnreinigung" in (s.get("motivName") or "").lower() or "pzr" in (s.get("motivId") or "")


def test_einsammeln_prophylaxe_setzt_spur():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": False, "frage": "arzt"})
    gehirn.einsammeln(sit, "Zur Prophylaxe bitte.")
    assert s["grund"] == "Zahnreinigung"
    assert s["arzt"]["calendarId"] == Z3
    assert s["arzt"].get("raeume") == [Z3, Z2]


def test_einsammeln_frau_thaler_laesst_grund_offen():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": False, "frage": "arzt"})
    gehirn.einsammeln(sit, "Bei Frau Thaler.")
    assert s["arzt"]["calendarId"] == EVA
    assert not s.get("grund")
    fid, frage = gehirn.naechste_frage(sit)
    assert fid == "grund", (fid, frage)
