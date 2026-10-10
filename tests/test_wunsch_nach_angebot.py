"""Wunschtermine nach dem ersten Slotangebot (10.10.2026).

Chef: "wenn ein patient den angebotenen Termin ablehnt und sagt ich kann nur
dienstags oder ich kann erst ab 16 Uhr ... hat sie oft dann einfach das
ueberhoert und frei weiter gesucht oder immer den gleichen termin angeboten"
und "auf gibt es keinen frueheren Termin antworten dass das der frueheste ist
(wenn das stimmt)".
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from bianca import flow, gehirn, hintergrund, session
from kern.slots import (
    fragt_nach_frueherem_slot,
    pick_slots,
    slot_praeferenz_aenderung,
)
from kern.tenants import laden

_MONTAG = date.today() + timedelta(days=(7 - date.today().weekday()) % 7 + 7)


def _iso(tage: int, stunde: int, minute: int = 0) -> str:
    tag = _MONTAG + timedelta(days=tage)
    return datetime.combine(tag, time(stunde, minute)).astimezone().isoformat(timespec="seconds")


MO_09 = _iso(0, 9)
MO_14 = _iso(0, 14)
DI_10 = _iso(1, 10)
MI_10 = _iso(2, 10)
MI_1630 = _iso(2, 16, 30)
DI2_10 = _iso(8, 10)
DI2_17 = _iso(8, 17)
FR2_1615 = _iso(11, 16, 15)
VORRAT = [MO_09, MO_14, DI_10, MI_10, MI_1630, DI2_10, DI2_17, FR2_1615]


def _buchung(tenant: str = "meddent") -> dict:
    sit = session.neu(tenant=laden(tenant))
    s = gehirn.sammler(sit)
    cal = (sit.get("tenant") or laden(tenant)).get("calendars") or [{}]
    s.update({
        "modus": "buchen", "phase": "", "frage": "", "warSchonMal": False,
        "arzt": {"typ": "gesagt", "calendarId": cal[0].get("id") or "x",
                 "calendarName": cal[0].get("name") or "Doktor Test"},
        "grund": "Kontrolle", "grundWortlaut": "Kontrolle",
        "motivId": "qOQCI4vV2EhQVmKmRqdu", "motivName": "KCH Kontrolluntersuchung",
        "nachname": "Muster", "vorname": "Max", "buchstabiert": True,
        "nameVerified": True, "versicherung": "gesetzlich",
        "wunsch": {"erstmoeglich": True}, "wunschText": "frühestmöglich",
        "pzr": "nein", "bleaching": "nein", "rueckblick": "gefragt",
    })
    sit["slotVorrat"] = list(VORRAT)
    sit["vorratFuer"] = hintergrund.vorrat_schluessel(sit)
    sit["vorratGemerkt"] = True
    return sit


@pytest.fixture(autouse=True)
def _kein_kalender(monkeypatch):
    """Nachladen liefert denselben Vorrat — kein Netz."""
    from kern import calendar as kal

    def fake(*_a, **_k):
        return {"ok": True, "slots": list(VORRAT)}

    for name in ("find_slots", "find_slots_behandler", "find_slots_raeume"):
        if hasattr(kal, name):
            monkeypatch.setattr(kal, name, fake)


def _angeboten(sit) -> list[str]:
    return [o["iso"] for o in sit.get("offered") or []]


# --- W-PASST-NICHT ---------------------------------------------------------

@pytest.mark.parametrize("satz", [
    "Passt leider auch nicht.", "Geht nicht.", "Der passt mir gar nicht.",
    "Nein, der passt auch nicht.", "Klappt bei mir nicht.",
])
def test_passt_nicht_ist_nein(satz):
    assert gehirn.ist_nein(satz)
    assert not flow._slot_wahl(satz, [{"iso": MO_09}])


@pytest.mark.parametrize("satz", [
    "Passt.", "Ja, passt.", "Passt, nicht wahr?", "Passt gut.", "Gerne, der passt.",
])
def test_gegenprobe_passt_bleibt_zusage(satz):
    assert not gehirn.ist_nein(satz)
    assert flow._slot_wahl(satz, [{"iso": MO_09}]) == MO_09


def test_auch_nicht_ist_ablehnung_aller_angebote():
    a = slot_praeferenz_aenderung("Nein, der passt auch nicht.", offered_isos=[DI2_17])
    assert a and a.get("rejectAll") and DI2_17 in a["excludeIsos"]


# --- W-WUNSCH-HART: "nur dienstags" / "erst ab 16 Uhr" ----------------------

def test_nur_dienstags_ist_harte_grenze_lieber_nicht():
    hart = slot_praeferenz_aenderung("Nein, ich kann nur dienstags.", offered_isos=[MO_09])
    weich = slot_praeferenz_aenderung("Nein, lieber Mittwoch vormittags.", offered_isos=[MO_09])
    assert hart["weekdays"] == [2] and hart.get("tageHart")
    assert not weich.get("tageHart")
    ab16 = slot_praeferenz_aenderung("Das geht leider nicht, ich kann erst ab 16 Uhr.",
                                     offered_isos=[MO_09])
    assert ab16["hourMin"] == 16 and ab16.get("zeitHart")


def test_harter_wochentag_faellt_nie_auf_anderen_tag():
    wunsch = {"weekdays": [2], "tageHart": True, "hourMin": 12, "hourMax": 18,
              "excludeIsos": [DI2_17]}
    r = pick_slots([MO_09, MI_1630, DI2_10, FR2_1615], wish=wunsch)
    assert [s["iso"] for s in r["slots"]] == [DI2_10]
    assert r["wishMatched"] is False


def test_gegenprobe_lieber_wochentag_darf_ausweichen():
    wunsch = {"weekdays": [2], "hourMin": 12, "hourMax": 18, "excludeIsos": [DI2_17]}
    r = pick_slots([MO_09, MI_1630, FR2_1615], wish=wunsch)
    assert r["slots"], "weiche Vorliebe faellt stufenweise wie bisher"


def test_erst_ab_16_bietet_nie_den_vormittag():
    wunsch = {"hourMin": 16, "hourMax": 21, "zeitHart": True, "excludeIsos": [MI_1630]}
    r = pick_slots([MO_09, DI_10, MI_1630], wish=wunsch)
    assert r["slots"] == []


def test_live_nur_dienstags_nachmittags_dann_nein_bleibt_dienstag():
    sit = _buchung()
    flow._angebot(sit)
    assert _angeboten(sit) == [MO_09]

    aus = flow.zug(sit, "Nein, das passt nicht. Ich kann nur dienstags.")
    assert "vormittags oder nachmittags" in aus["text"]

    flow.zug(sit, "Nachmittags.")
    assert _angeboten(sit) == [DI2_17]

    aus = flow.zug(sit, "Nein, der passt auch nicht.")
    angebot = _angeboten(sit)
    assert angebot and angebot != [DI2_17], "nie derselbe Termin erneut"
    assert all(datetime.fromisoformat(i).isoweekday() == 2 for i in angebot)
    assert "Wann würde es Ihnen" not in aus["text"]


def test_live_erst_ab_16_dann_tag():
    sit = _buchung()
    flow._angebot(sit)
    aus = flow.zug(sit, "Das geht leider nicht, ich kann erst ab 16 Uhr.")
    assert "An welchem Tag" in aus["text"]
    flow.zug(sit, "Mittwoch.")
    assert _angeboten(sit) == [MI_1630]


def test_dienstags_ab_16_in_einem_satz_sucht_sofort():
    sit = _buchung()
    flow._angebot(sit)
    flow.zug(sit, "Nein, ich kann nur dienstags ab 16 Uhr.")
    assert _angeboten(sit) == [DI2_17]


def test_wunsch_bekannt_fragt_nach_ablehnung_nicht_erneut():
    sit = _buchung()
    flow._angebot(sit)
    flow.zug(sit, "Nein, ich kann nur dienstags ab 16 Uhr.")
    aus = flow.zug(sit, "Nein.")
    assert "An welchem Tag" not in aus["text"]
    assert "vormittags oder nachmittags" not in aus["text"]
    assert DI2_17 not in _angeboten(sit)


# --- W-FRUEHER-FRAGE ----------------------------------------------------------

def test_frage_frueher_erkennt_auch_geht_es_auch_frueher():
    assert fragt_nach_frueherem_slot("Geht es auch früher?")
    assert not fragt_nach_frueherem_slot("Ich kann nicht früher.")


def test_frueher_frage_bietet_frueheren_passenden_termin():
    sit = _buchung()
    flow._angebot(sit)
    gehirn.sammler(sit)["wunsch"] = {"weekdays": [2], "tageHart": True}
    sit["offered"] = [{"iso": DI2_10}]
    gehirn.sammler(sit).update({"phase": "angebot", "frage": "slotwahl"})

    aus = flow.zug(sit, "Gibt es nichts früher?")
    assert _angeboten(sit) == [DI_10], "frueherer Dienstag statt Pauschalsatz"
    assert "frühestmögliche" not in aus["text"]
    assert aus["text"].rstrip().endswith("?")


def test_frueher_frage_ehrlich_wenn_wirklich_frueheste():
    sit = _buchung()
    flow._angebot(sit)
    assert _angeboten(sit) == [MO_09]
    aus = flow.zug(sit, "Gibt es keinen früheren Termin?")
    assert _angeboten(sit) == [MO_09]
    assert "früheste" in aus["text"] and aus["text"].endswith("?")


def test_frueher_frage_bricht_nur_dienstags_nicht():
    sit = _buchung()
    flow._angebot(sit)
    flow.zug(sit, "Nein, ich kann nur dienstags ab 16 Uhr.")
    assert _angeboten(sit) == [DI2_17]
    aus = flow.zug(sit, "Geht es auch früher?")
    assert all(datetime.fromisoformat(i).isoweekday() == 2 for i in _angeboten(sit))
    assert "zu Ihren Angaben" in aus["text"]


def test_notaus_frueher_ehrlich_behaelt_pauschalsatz(monkeypatch):
    monkeypatch.setenv("FRUEHER_EHRLICH", "0")
    sit = _buchung()
    flow._angebot(sit)
    aus = flow.zug(sit, "Gibt es keinen früheren Termin?")
    assert "frühestmögliche" in aus["text"]
