"""Thaler Grund→Zimmer (Chef 08.09.2026).

PZR: Zimmer 3, sonst 2. Notfall: Zimmer 1. Rest: Zimmer 4 bei Thaler.
MedDent ohne Karte bleibt unverändert.
"""

from __future__ import annotations

from datetime import datetime

from bianca import gehirn
from kern import calendar as kal
from kern import gespraech
from kern import tenants as kern_tenants
from kern import zimmer_map
from kern.tenants import laden
from tests.test_funktionskalender import EVA, Z1, Z2, Z3, Z4, _sit, _thaler


def test_zimmer_nr_aus_namen():
    assert kern_tenants.zimmer_nr("Zimmer 3 Prophylaxe") == 3
    assert kern_tenants.zimmer_nr("Zimmer 1") == 1
    assert kern_tenants.zimmer_nr("Irem (Zi 4)") == 4
    assert kern_tenants.zimmer_nr("Leonita (Zi2)") == 2
    assert kern_tenants.zimmer_nr("Dr. Eva Thaler") is None


def test_gruppe_pzr_akut_behandlung():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"grund": "Zahnreinigung", "motivId": "pzr",
              "motivName": "PRO professionelle Zahnreinigung"})
    assert zimmer_map.gruppe(s) == "pzr"
    s.update({"grund": "akute Beschwerden", "motivId": "akut",
              "motivName": "KCH Akute Beschwerden / Notfall",
              "grundWortlaut": "Ich habe Zahnschmerzen"})
    assert zimmer_map.gruppe(s) == "akut"
    s.update({"grund": "Füllung", "motivId": "fuell",
              "motivName": "KCH Füllung klein",
              "grundWortlaut": "Füllung"})
    assert zimmer_map.gruppe(s) == "behandlung"


def test_raeume_pzr_erst_drei_dann_zwei():
    t = _thaler()
    ids = [c["id"] for c in zimmer_map.raeume(t, "pzr")]
    assert ids == [Z3, Z2], ids
    assert [c["id"] for c in zimmer_map.raeume(t, "akut")] == [Z1]
    assert [c["id"] for c in zimmer_map.raeume(t, "behandlung")] == [Z4]


def test_meddent_ohne_zimmer_karte():
    t = laden("meddent")
    assert not zimmer_map.aktiv(t)
    assert zimmer_map.raeume(t, "pzr") == []


def test_pzr_sucht_zimmer3_dann_zimmer2():
    """Zimmer 3 leer → Zimmer 2 gewinnt, Buchung bindet Z2."""
    gesehen = []

    def fake(tenant, ctx, *, start_date="", egal=False, source=""):
        cid = ctx.get("calendarId")
        gesehen.append(cid)
        if cid == Z3:
            return {"ok": True, "slots": []}
        if cid == Z2:
            return {"ok": True, "slots": ["2026-09-10T09:00:00+02:00"]}
        return {"ok": True, "slots": ["2026-09-11T08:00:00+02:00"]}

    echt = kal.find_slots
    kal.find_slots = fake
    try:
        found = kal.find_slots_raeume(
            _thaler(),
            {"visitMotiveId": "pzr", "visitMotiveName": "Zahnreinigung"},
            zimmer_map.raeume(_thaler(), "pzr"),
        )
        assert gesehen == [Z3, Z2], gesehen
        assert found["calendar"]["id"] == Z2
        assert found["slots"]
    finally:
        kal.find_slots = echt


def test_notfall_landet_zimmer1():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "grund": "Zahnschmerzen", "motivId": "akut",
        "motivName": "KCH Akute Beschwerden / Notfall",
        "grundWortlaut": "starke Schmerzen",
        "arzt": {"typ": "default", "calendarId": EVA, "calendarName": "Dr. Eva Thaler"},
    })
    gehirn.kalender_zu_grund(sit)
    assert s["arzt"]["calendarId"] == Z1
    assert s["arzt"]["raeume"] == [Z1]
    assert s["arzt"]["calendarName"] == "Dr. Eva Thaler"


def test_behandlung_landet_zimmer4():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({
        "modus": "buchen",
        "grund": "Kontrolle", "motivId": "recall",
        "motivName": "Recall Check-up",
        "arzt": {"typ": "default", "calendarId": EVA, "calendarName": "Dr. Eva Thaler"},
    })
    gehirn.kalender_zu_grund(sit)
    assert s["arzt"]["calendarId"] == Z4
    assert s["arzt"]["raeume"] == [Z4]


def _thaler_live():
    """Wie die echte DB: Eva + Prophylaxe, Zimmer nur als rooms."""
    return {
        "clientId": zimmer_map.THALER_CLIENT,
        "locationId": "loc",
        "praxisName": "Zahnarztpraxis Eva Thaler",
        "defaultCalendarId": EVA,
        "zimmerMap": dict(zimmer_map.DEFAULT_MAP),
        "calendars": [
            {"id": EVA, "name": "Dr. Eva Thaler"},
            {"id": "cal-prophy", "name": "Prophylaxe"},
        ],
        "rooms": [
            {"id": "r1", "name": "Zi1 Notfall"},
            {"id": "r2", "name": "Zi2 PZR"},
            {"id": "r3", "name": "Zi3 PZR"},
            {"id": "r4", "name": "Zi4 Thaler"},
        ],
    }


def test_live_ohne_zimmer_kalender_pzr_auf_prophylaxe():
    t = _thaler_live()
    ids = [c["id"] for c in zimmer_map.raeume(t, "pzr")]
    assert ids == ["cal-prophy"], ids
    assert [c["id"] for c in zimmer_map.raeume(t, "akut")] == [EVA]
    assert [c["id"] for c in zimmer_map.raeume(t, "behandlung")] == [EVA]


def test_live_prophylaxe_satz_bindet_prophylaxe_kalender():
    sit = {
        "tenant": _thaler_live(),
        "messages": [{"role": "system", "content": "x"}],
        "motivKatalog": [],
    }
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "warSchonMal": False, "frage": "arzt"})
    gehirn.einsammeln(sit, "Zur Prophylaxe.")
    assert s["arzt"]["calendarId"] == "cal-prophy"
    assert s["arzt"]["calendarName"] == "Prophylaxe"


def test_jetzt_ist_kein_unklar():
    for satz in ("Jetzt", "Jetzt!", "Sofort.", "Heute"):
        assert not gespraech.wirkt_unklar(satz), satz


def test_jetzt_auf_wunsch_ist_heute():
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "frage": "wunsch"})
    gehirn.einsammeln(sit, "Jetzt!")
    w = s.get("wunsch") or {}
    assert w.get("date") == datetime.now(gehirn.TZ).date().isoformat(), w
