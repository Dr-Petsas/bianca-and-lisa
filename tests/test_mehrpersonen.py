"""Paket 4: Mehrpersonen-Termin — zwei getrennte Buchungsaufgaben.

Verankert am Live-Replay ``blessing-zweipersonen`` (tests/live_replays.py):
„für zwei Personen, ich und meine Mutter, Anton Beispiel und Eva Beispiel"
muss ZWEI Termine ergeben; ein einzelner Dritt-Termin („für meine Mutter")
bleibt EINE Aufgabe. Die Gegenproben sind der teurere Teil.
"""
from __future__ import annotations

import pytest

from bianca import agent, gehirn
from kern import hirn, mehrpersonen
from tests.live_replays import replay


# --- Detektor ---------------------------------------------------------------

def test_replay_zweipersonen_liefert_eine_zusatzperson():
    r = replay("blessing-zweipersonen")
    zusatz = mehrpersonen.erkenne(r.anrufer[0])
    assert len(zusatz) == 1
    p = zusatz[0]
    assert p["rolle"] == "mutter"
    assert p["nachname"] == "Beispiel"
    assert p["vorname"] == "Eva"


def test_gegenprobe_einzelner_dritttermin_ist_keine_mehrpersonen():
    r = replay("blessing-zweipersonen")
    assert mehrpersonen.erkenne(r.gegenprobe[0]) == []


@pytest.mark.parametrize("satz", [
    "Ich hätte gern einen Termin für meine Mutter.",
    "Einen Termin für meinen Sohn bitte.",
    "Ich brauche einen Kontrolltermin.",
    "Ich und mein Anliegen sind dringend.",      # kein Personen-Enum
    "Guten Tag, ich möchte einen Termin.",
])
def test_einzelwunsch_schlaegt_nicht_an(satz):
    assert mehrpersonen.erkenne(satz) == []


@pytest.mark.parametrize("satz", [
    "Ich bräuchte Termine für zwei Personen.",
    "Für uns beide bitte einen Termin.",
    "Ich und meine Frau möchten einen Termin.",
])
def test_mehrpersonen_ohne_namen_liefert_zusatz(satz):
    zusatz = mehrpersonen.erkenne(satz)
    assert len(zusatz) >= 1


def test_drei_personen_liefert_zwei_zusatz():
    zusatz = mehrpersonen.erkenne(
        "Für drei Personen: ich und meine Mutter und mein Sohn."
    )
    assert len(zusatz) == 2
    assert {p["rolle"] for p in zusatz} == {"mutter", "sohn"}


def test_notaus(monkeypatch):
    monkeypatch.setenv("MEHRPERSONEN", "0")
    assert mehrpersonen.erkenne(
        "Für zwei Personen, ich und meine Mutter."
    ) == []


# --- Agent-Verdrahtung: zweite Buchung wird geparkt -------------------------

def _booking_sit():
    sit: dict = {"stimme": "Bianca"}
    hirn.anwenden(sit, {"zug": "wechseln", "kanal": "ok",
                        "handlung": "ANLEGEN", "gegenstand": "VORGANG"})
    assert hirn.modus_von(hirn.aktiv(sit)) == "buchen"
    return sit


def test_aufteilen_parkt_zweite_buchung(monkeypatch):
    monkeypatch.setenv("HIRN_AUTO_RESUME", "enforce")
    sit = _booking_sit()
    agent._mehrpersonen_aufteilen(
        sit,
        "Ich bräuchte einen Termin, für zwei Personen, ich und meine "
        "Mutter, Anton Beispiel und Eva Beispiel.",
    )
    assert sit.get("mehrpersonenGeteilt") is True
    geparkt = [a for a in hirn.hirn(sit)["anliegen"]
               if a.get("status") == "geparkt"]
    assert len(geparkt) == 1
    cp = geparkt[0].get("checkpoint") or {}
    seed = cp.get("sammler") or {}
    assert seed.get("modus") == "buchen"
    assert seed.get("fuerWen") == "mutter"
    assert seed.get("nachname") == "Beispiel"
    # Der Seed ist ein vollständiger Sammler (kein KeyError im Fluss).
    for k in gehirn.FELDER_START:
        assert k in seed


def test_aufteilen_nur_einmal(monkeypatch):
    monkeypatch.setenv("HIRN_AUTO_RESUME", "enforce")
    sit = _booking_sit()
    satz = "Für zwei Personen, ich und meine Mutter."
    agent._mehrpersonen_aufteilen(sit, satz)
    agent._mehrpersonen_aufteilen(sit, satz)
    geparkt = [a for a in hirn.hirn(sit)["anliegen"]
               if a.get("status") == "geparkt"]
    assert len(geparkt) == 1


def test_aufteilen_ohne_aktive_buchung_passiert_nichts(monkeypatch):
    monkeypatch.setenv("HIRN_AUTO_RESUME", "enforce")
    sit: dict = {"stimme": "Bianca"}
    agent._mehrpersonen_aufteilen(
        sit, "Für zwei Personen, ich und meine Mutter.")
    assert not sit.get("mehrpersonenGeteilt")
    assert "hirn" not in sit or not [
        a for a in hirn.hirn(sit).get("anliegen", [])
        if a.get("status") == "geparkt"]


def test_einzeldritttermin_parkt_nichts(monkeypatch):
    monkeypatch.setenv("HIRN_AUTO_RESUME", "enforce")
    sit = _booking_sit()
    agent._mehrpersonen_aufteilen(
        sit, "Ich hätte gern einen Termin für meine Mutter.")
    assert not sit.get("mehrpersonenGeteilt")
    assert not [a for a in hirn.hirn(sit)["anliegen"]
                if a.get("status") == "geparkt"]
