"""Paket 6: Negative Terminaussagen + Platzhalter-Anrede evidenzpflichtig.

Replays ``thaler-negativ`` (negative Suchaussage ohne echte Suche) und
``meddent-platzhalter`` (Platzhalter-Name „Frau SMS" nie als Anrede).
"""
from __future__ import annotations

import pytest

from kern import anrede_wache, fakten_wache
from tests.live_replays import replay


# --- Negative Terminaussage ohne echte Suche --------------------------------

def _tool_bestand(leer=True, count=0, ok=True, **extra):
    e = {"name": "agentFindPatientAppointments", "ok": ok,
         "resultCount": count}
    e.update(extra)
    return e


def test_replay_negativ_ohne_suche_ist_unbelegt(monkeypatch):
    monkeypatch.setenv("FAKTEN_WACHE", "enforce")
    sit = {"stimme": "Bianca", "sammler": {}, "tools": []}  # keine Suche gelaufen
    # Die live gesprochene (leicht verhörte) Negativ-Aussage:
    behauptung = "Ich habe hier aktuell keine Termine für eine gefunden."
    assert fakten_wache.unbelegte_behauptung(sit, behauptung) == "bestand"


def test_negativ_mit_echter_suche_ist_belegt(monkeypatch):
    monkeypatch.setenv("FAKTEN_WACHE", "enforce")
    sit = {"stimme": "Bianca", "sammler": {},
           "tools": [_tool_bestand(count=0)]}  # Suche lief, 0 Treffer
    behauptung = "Ich habe hier aktuell keine Termine für Sie gefunden."
    assert fakten_wache.unbelegte_behauptung(sit, behauptung) == ""


def test_ehrliche_buchungsverneinung_kein_bestand_claim():
    """„Ich habe keinen Termin gebucht" darf die NEUE Bestands-Regex nicht
    triggern (die Slot-Negativ-Regex ist eine andere, pre-existente Wache)."""
    assert fakten_wache._CLAIM_BESTAND_NEGATIV.search(
        "Ich habe für Sie noch keinen Termin gebucht.") is None


@pytest.mark.parametrize("satz", [
    "Ich habe keine Termine für Sie gefunden.",
    "Wir haben aktuell keine weiteren Termine für Sie gefunden.",
    "Ich habe leider keinen Termin vorliegen.",
])
def test_negativ_formen_erkannt(satz):
    assert fakten_wache._CLAIM_BESTAND_NEGATIV.search(satz) is not None


@pytest.mark.parametrize("satz", [
    "Ich habe keine Zeit mehr für heute.",
    "Ich habe keinen anderen Wunsch.",
])
def test_negativ_formen_ohne_termin_bleiben_frei(satz):
    assert fakten_wache._CLAIM_BESTAND_NEGATIV.search(satz) is None


# --- Platzhalter-Name nie als Anrede ----------------------------------------

def test_replay_platzhalter_wird_nicht_als_anrede_gesprochen():
    r = replay("meddent-platzhalter")
    sit = {
        "stimme": "Bianca",
        "sammler": {"vorname": "Reservierung", "nachname": "SMS",
                    "name": "Reservierung SMS"},
    }
    neu, gestrichen = anrede_wache.saeubern(
        sit, "Gerne, Frau SMS. Ich schaue nach Ihrem Termin.")
    assert "Frau SMS" not in neu
    assert "SMS" not in neu
    assert gestrichen
    assert r.tenant == "meddent"


def test_echte_anrede_bleibt():
    sit = {
        "stimme": "Bianca",
        "sammler": {"vorname": "Stefan", "nachname": "Beispiel",
                    "name": "Stefan Beispiel"},
    }
    neu, gestrichen = anrede_wache.saeubern(
        sit, "Gerne, Herr Beispiel. Ich schaue nach Ihrem Termin.")
    assert "Herr Beispiel" in neu
    assert not gestrichen


def test_platzhalter_nicht_in_belegten_namen():
    sit = {"stimme": "Bianca",
           "sammler": {"vorname": "Reservierung", "nachname": "SMS",
                       "name": "Reservierung SMS"}}
    erlaubt = anrede_wache.belegte_namen(sit)
    assert "sms" not in erlaubt
