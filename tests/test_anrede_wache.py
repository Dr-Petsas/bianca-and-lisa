"""W-ANREDE (13.09.2026): Bianca spricht keinen erfundenen Namen aus.

Live-Probe 12.09.2026 (tools/_probe_langgespraech.py, unbekannter Anrufer
ohne uebermittelte Rufnummer): erster Zug „Einen Moment. Gerne, Herr Meier.
Ich buche Ihnen einen Termin zur Kontrolle." — „Meier" hat niemand gesagt.

Die Gegenprobe ist genauso wichtig: eine BELEGTE Anrede (Anrufer hat sich
vorgestellt, Kartei-Treffer, Behandler des Mandanten) darf der Waechter nie
antasten — sonst verliert Bianca ihre persoenliche Ansprache.

Offline: kein LLM, kein Netz.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bianca import agent as bianca_agent
from bianca import gehirn
from kern import anrede_wache, llm


def _tenant() -> dict:
    return {
        "praxisName": "Zahnärzte im Medical Center Düsseldorf",
        "mandantId": "meddent",
        "calendars": [
            {"calendarId": "c1", "name": "Dr. Petsas"},
            {"calendarId": "c2", "name": "Doktor Theodosios Patrikis"},
        ],
    }


def _sit(**felder) -> dict:
    sit = {"tenant": _tenant(), "sammler": {}}
    sit.update(felder)
    return sit


# ---------------------------------------------------------------------------
# Erfundene Anrede fliegt raus
# ---------------------------------------------------------------------------

def test_erfundener_name_wird_gestrichen():
    sit = _sit()
    neu, weg = anrede_wache.saeubern(
        sit, "Gerne, Herr Meier. Ich buche Ihnen einen Termin zur Kontrolle.")
    assert weg == ["Herr Meier"]
    assert neu == "Gerne. Ich buche Ihnen einen Termin zur Kontrolle."


def test_erfundener_name_am_satzanfang():
    sit = _sit()
    neu, weg = anrede_wache.saeubern(sit, "Frau Schneider, das habe ich notiert.")
    assert weg == ["Frau Schneider"]
    # Gross geschrieben — der Satz faengt jetzt von vorn an.
    assert neu == "Das habe ich notiert."


def test_erfundener_name_mit_titel():
    sit = _sit()
    _, weg = anrede_wache.saeubern(sit, "Guten Tag, Frau Doktor Sommer.")
    assert weg == ["Frau Doktor Sommer"]


# ---------------------------------------------------------------------------
# Belegte Anrede bleibt — das ist der teurere Fehler
# ---------------------------------------------------------------------------

def test_genannter_nachname_bleibt():
    sit = _sit()
    sit["sammler"] = {"nachname": "Meier", "geschlecht": "m"}
    neu, weg = anrede_wache.saeubern(sit, "Gerne, Herr Meier. Ich schaue nach.")
    assert weg == []
    assert neu == "Gerne, Herr Meier. Ich schaue nach."


def test_erkannter_anrufer_bleibt():
    sit = _sit(anrufer={"vorname": "Eva", "nachname": "Thaler"})
    _, weg = anrede_wache.saeubern(sit, "Schön, Sie zu hören, Frau Thaler.")
    assert weg == []


def test_kontaktname_bei_drittterminen_bleibt():
    sit = _sit()
    sit["sammler"] = {"kontaktName": "Tzannis", "fuerWen": "sohn"}
    _, weg = anrede_wache.saeubern(sit, "Alles klar, Herr Tzannis.")
    assert weg == []


def test_behandler_des_mandanten_bleiben():
    sit = _sit()
    for satz in ("Herrn Doktor Petsas verbinde ich gern.",
                 "Möchten Sie zu Frau Doktor Patrikis?"):
        _, weg = anrede_wache.saeubern(sit, satz)
        assert weg == [], satz


def test_titel_ohne_namen_bleibt():
    sit = _sit()
    for satz in ("Einen Moment, Herr Doktor.", "Gerne, Frau Doktor."):
        _, weg = anrede_wache.saeubern(sit, satz)
        assert weg == [], satz


def test_hoeflichkeit_ohne_namen_bleibt():
    sit = _sit()
    _, weg = anrede_wache.saeubern(sit, "Sagen Sie mir bitte, ob Herr oder Frau?")
    assert weg == []


def test_maschinen_anrede_geht_immer_durch():
    """gehirn.anrede baut die Anrede aus dem Sammler — sie ist per
    Definition belegt und darf nie am Waechter haengen."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s.update({"nachname": "Berger", "vorname": "Martin", "geschlecht": "m"})
    text = f"Soll ich den Termin wirklich absagen, {gehirn.anrede(s)}?"
    neu, weg = anrede_wache.saeubern(sit, text)
    assert weg == []
    assert neu == text


# ---------------------------------------------------------------------------
# Einhaengung im Agenten
# ---------------------------------------------------------------------------

def test_agent_wache_streicht_und_spurt():
    sit = _sit()
    raus = bianca_agent._anrede_wache_anwenden(
        sit, "Gerne, Herr Meier. Was darf ich eintragen?")
    assert "Meier" not in raus
    assert raus.startswith("Gerne.")
    spuren = [e for e in (sit.get("_spur") or []) if e.get("w") == "anrede-wache"]
    assert spuren, "der Eingriff muss in der Wächter-Spur stehen"


def test_shadow_aendert_nichts(monkeypatch):
    monkeypatch.setenv("ANREDE_WACHE", "shadow")
    sit = _sit()
    text = "Gerne, Herr Meier. Was darf ich eintragen?"
    assert bianca_agent._anrede_wache_anwenden(sit, text) == text


def test_notaus_haelt_die_wache_an(monkeypatch):
    monkeypatch.setenv("ANREDE_WACHE", "off")
    sit = _sit()
    text = "Gerne, Herr Meier. Was darf ich eintragen?"
    assert bianca_agent._anrede_wache_anwenden(sit, text) == text


def test_vorab_und_endtext_werden_gleich_gesaeubert(monkeypatch):
    """P5 spricht Saetze sofort. Wuerden Gesprochenes und Endtext
    unterschiedlich gesaeubert, faende llm.rest_nach_vorab den Rest nicht
    mehr — der Satz kaeme ein zweites Mal."""
    sit = _sit()
    satz = "Gerne, Herr Meier."
    gesprochen = bianca_agent._anrede_wache_anwenden(sit, satz)
    endtext = bianca_agent._anrede_wache_anwenden(
        sit, "Gerne, Herr Meier. Ich schaue in den Kalender.")
    assert gesprochen == "Gerne."
    assert endtext.startswith(gesprochen)
    assert llm.rest_nach_vorab([gesprochen], endtext).strip() == (
        "Ich schaue in den Kalender.")


@pytest.mark.parametrize("text", [
    "",
    "Ich schaue eben in den Kalender.",
    "Das sind 120 Euro, im Einzelfall kann das abweichen.",
])
def test_saetze_ohne_anrede_bleiben_unberuehrt(text):
    sit = _sit()
    neu, weg = anrede_wache.saeubern(sit, text)
    assert weg == []
    assert neu == text.strip()
