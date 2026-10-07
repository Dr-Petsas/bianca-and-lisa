"""W-GESPRAECH-WUNSCH (07.10.2026, Anruf 238b637a): Gesprächswunsch mit Arzt.

Live: „Ich hätte gerne einmal mit dem Doktor Patrikis gesprochen, bitte.“ und
„Nur ein Gespräch mit Doktor Patrikis, bitte.“ wurden nicht als
Durchstell-Wunsch erkannt. Die Gegenproben (Besprechung ≠ Durchstellen,
prod-no-regressions Regel 1) sind der wichtigere Teil.
"""

import pytest

from bianca import flow, gehirn, weiterleiten
from kern.tenants import laden


def _sit(mandant: str = "meddent") -> dict:
    return {"tenant": laden(mandant), "messages": [{"role": "system", "content": "x"}]}


@pytest.mark.parametrize("satz", [
    "Ich hätte gerne einmal mit dem Doktor Patrikis gesprochen, bitte.",
    "Nur ein Gespräch mit Doktor Patrikis, bitte.",
])
def test_live_gespraechswunsch_stellt_durch(satz):
    sit = _sit()
    events: list[str] = []
    z = flow.zug(sit, satz, events.append)
    assert z and z.get("transfer", {}).get("nummer"), satz
    assert z.get("hangup") and weiterleiten.JINGLE_EVENT in events, satz
    assert (gehirn.sammler(sit)["arzt"] or {}).get("calendarName") == "Dr. Patrikis"


@pytest.mark.parametrize("satz", [
    "Ich hätte gern ein Beratungsgespräch bei Doktor Petsas.",
    "Vorgespräch für ein Implantat bei Doktor Patrikis.",
    "Ich habe schon mit Doktor Petsas gesprochen, ich brauche einen Termin.",
    "Ich habe mit Doktor Petsas gesprochen, er meinte, ich soll mich melden.",
    "Ich hatte ein Gespräch mit Doktor Patrikis über die Krone.",
    "Implantatbesprechung bei Doktor Petsas.",
    "ZE Besprechung bei Doktor Patrikis, bitte.",
])
def test_besprechung_und_erzaehlung_stellen_nie_durch(satz):
    sit = _sit()
    events: list[str] = []
    z = flow.zug(sit, satz, events.append)
    assert not (z or {}).get("transfer"), satz
    assert weiterleiten.JINGLE_EVENT not in events, satz


def test_kosten_verbunden_bleibt_sachfrage():
    sit = _sit()
    events: list[str] = []
    z = flow.zug(sit, "Ist das mit Kosten verbunden?", events.append)
    assert not (z or {}).get("transfer")
    assert weiterleiten.JINGLE_EVENT not in events


def test_gesperrter_behandler_bekommt_ehrlichen_hinweis():
    sit = _sit()
    events: list[str] = []
    z = flow.zug(sit, "Nur ein Gespräch mit Doktor Nikolaou, bitte.", events.append)
    assert z and not z.get("transfer")
    assert weiterleiten.JINGLE_EVENT not in events


@pytest.mark.parametrize("mandant", ["thaler", "blessing"])
def test_praxen_ohne_whitelist_stellen_nie_durch(mandant):
    sit = _sit(mandant)
    events: list[str] = []
    z = flow.zug(sit, "Nur ein Gespräch mit dem Doktor, bitte.", events.append)
    assert not (z or {}).get("transfer")
    assert weiterleiten.JINGLE_EVENT not in events


def test_notaus(monkeypatch):
    monkeypatch.setenv("GESPRAECH_WUNSCH", "0")
    assert not weiterleiten._gespraech_wunsch("Nur ein Gespräch mit Doktor Patrikis, bitte.")
