"""Paket 5: Sprechstunde-/ERREICHEN-Trennung + kontextuelle Dringlichkeit.

Verankert an den Live-Replays ``blessing-sprechstunde`` und
``blessing-dringlich`` (tests/live_replays.py). Die Gegenproben
(echter Sprech-/Verbinden-Wunsch bleibt ERREICHEN; „irgendwann ein
Kontrolltermin" bleibt normal) sind der teurere Teil.
"""
from __future__ import annotations

import pytest

from kern import dringlichkeit, intent
from tests.live_replays import replay


def _sit(tenant=None):
    return {"stimme": "Bianca", "sammler": {}, "tenant": tenant or {}}


# --- „Sprechstunde" ist ein Besuchsgrund, kein Verbinden-Wunsch -------------

def test_replay_sprechstunde_ist_keine_erreichen():
    r = replay("blessing-sprechstunde")
    d = intent._fallback(_sit(), r.anrufer[0])
    assert d["handlung"] != "ERREICHEN"
    assert d["handlung"] == "ANLEGEN"


def test_gegenprobe_echter_sprechwunsch_bleibt_erreichen():
    r = replay("blessing-sprechstunde")
    d = intent._fallback(_sit(), r.gegenprobe[0])
    assert d["handlung"] == "ERREICHEN"
    assert d["gegenstand"] == "PERSON"


@pytest.mark.parametrize("satz", [
    "Ich brauche einen Termin in der Sprechstunde.",
    "Gibt es morgen eine Sprechstunde?",
    "Wann ist Ihre Sprechzeit?",
])
def test_sprechstunde_nicht_erreichen_regex(satz):
    assert intent._FB_ERREICHEN_RE.search(satz) is None
    assert intent._WECHSEL_RE.search(satz) is None


@pytest.mark.parametrize("satz", [
    "Kann ich bitte mit Doktor Blessing sprechen?",
    "Ich möchte mit dem Arzt sprechen.",
    "Verbinden Sie mich bitte.",
])
def test_echter_sprechwunsch_regex(satz):
    assert intent._FB_ERREICHEN_RE.search(satz) is not None


# --- Kontextuelle Dringlichkeit (Dermatologie) ------------------------------

def test_replay_blutende_wunde_ist_akut():
    r = replay("blessing-dringlich")
    fenster = " ".join(r.anrufer)
    k = dringlichkeit.bewerten(fenster, "dermatologie")
    assert int(k["stufe"]) == 2
    assert k["kern"]


def test_gegenprobe_kontrolltermin_bleibt_normal():
    r = replay("blessing-dringlich")
    k = dringlichkeit.bewerten(r.gegenprobe[0], "dermatologie")
    assert int(k["stufe"]) == 0


@pytest.mark.parametrize("satz", [
    "Meine Wunde blutet wieder.",
    "Die Wunde ist offen und blutet.",
    "Es ist eine offene Wunde.",
])
def test_akute_hautbeschwerde_stufe2(satz):
    assert int(dringlichkeit.bewerten(satz, "dermatologie")["stufe"]) == 2


@pytest.mark.parametrize("satz", [
    "Ich hätte gern irgendwann einen Kontrolltermin.",
    "Ich möchte mein Muttermal mal kontrollieren lassen.",
    "Es ist dringend.",  # bloßes Dringlichkeitswort ohne Symptom = normal
])
def test_ohne_akutsymptom_bleibt_normal(satz):
    assert int(dringlichkeit.bewerten(satz, "dermatologie")["stufe"]) == 0


def test_notaus_dringlichkeit(monkeypatch):
    monkeypatch.setenv("DRINGLICHKEIT", "0")
    assert int(dringlichkeit.bewerten(
        "Meine Wunde blutet wieder.", "dermatologie")["stufe"]) == 0
