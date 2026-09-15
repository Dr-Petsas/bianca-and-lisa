"""W-ZEITEN-WACHE (15.09.2026) — keine erfundenen Öffnungszeiten.

Anlass: Live-Probe gegen den echten Rüther-Prompt (Ben, DID …4160). Der
Agent-Prompt aus dem Portal trägt dort keine Praxis-Tatsache, die
Standorteinstellungen stehen auf dem Portal-Default — und das Modell erfand
auf drei Fragen drei verschiedene Zeitpläne.

Die Gegenproben sind der wichtigere Teil: eine belegte Auskunft zu streichen
wäre der teurere Fehler (dann wüsste die Praxis ihre eigenen Zeiten nicht
mehr zu sagen), und Termin-Sätze mit Uhrzeit gehören dem Kalender.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kern import zeiten_wache
from kern.tenants import laden

# Die drei Live-Antworten des Modells, wortgleich aus der Probe vom 15.09.2026.
LIVE = [
    "Wir sind heute von 8 bis 12 Uhr und von 14 bis 16 Uhr für Sie da.",
    "Wir sind montags, mittwochs und freitags von 8 bis 12 Uhr sowie "
    "dienstags und donnerstags von 14 bis 18 Uhr für Sie da.",
    "Ja, wir sind freitags von 8 bis 12 Uhr für Sie da.",
]


def _sit(tenant: dict) -> dict:
    return {"tenant": tenant, "_spur": []}


def _ruether() -> dict:
    """Ruether wie live: Praxis-Prompt ohne Zeiten, Portal-Default verworfen."""
    t = laden("ruether")
    t["dbPrompt"] = (
        "Das aktuelle Datum ist 2026-09-15T12:37:00+02:00. "
        "Sprich die Anruferin mit Sie an. Halte dich exakt an das Skript."
    )
    return t


# --- Belegt oder nicht ------------------------------------------------------
def test_ruether_hat_keine_belegten_zeiten():
    assert zeiten_wache.zeiten_belegt(_ruether()) is False
    assert zeiten_wache.aktiv(_sit(_ruether())) is True


def test_meddent_prompt_zeile_gilt_als_belegt():
    """MedDent traegt EINE Zeile im Agent-Prompt — die findet schon der
    Einzeiler-Parser von kern.wissen."""
    t = laden("meddent")
    t["dbPrompt"] = (
        "[Zeit?] - Öffnungszeiten: Mo - Do: 08:00 - 18:00 Uhr, "
        "Fr: 08:00 - 16:00 Uhr und nach Vereinbarung"
    )
    assert zeiten_wache.zeiten_belegt(t) is True
    assert zeiten_wache.aktiv(_sit(t)) is False


def test_thaler_sprechzeiten_block_gilt_als_belegt():
    """Thaler/Blessing schreiben einen mehrzeiligen Block ohne „Zeiten:“-Kopf
    — dafuer ist die grosszuegige Prompt-Pruefung da."""
    t = laden("thaler")
    t["dbPrompt"] = "SPRECHZEITEN\nMontag bis Donnerstag 8:00 - 18:00 Uhr\nFreitag 8:00 - 14:00"
    assert zeiten_wache.zeiten_belegt(t) is True


def test_gepflegte_standorteinstellungen_gelten_als_belegt():
    t = laden("thaler")
    t["dbPrompt"] = ""
    t["standort"] = {"text": "montags bis donnerstags 8 Uhr bis 18 Uhr"}
    assert zeiten_wache.zeiten_belegt(t) is True


def test_lokales_wissen_gilt_als_belegt():
    t = {"wissen": {"oeffnungszeiten": "montags bis freitags 9 bis 17 Uhr"}}
    assert zeiten_wache.zeiten_belegt(t) is True


def test_ohne_mandant_ist_die_wache_aus():
    """Fail-safe: kein Mandant (Unit-Tests, Docks) => nie eingreifen."""
    assert zeiten_wache.zeiten_belegt(None) is True
    assert zeiten_wache.zeiten_belegt({}) is True
    assert zeiten_wache.aktiv({"tenant": {}}) is False
    assert zeiten_wache.aktiv(None) is False


# --- Erkennung: die drei Live-Saetze ---------------------------------------
def test_die_drei_live_erfindungen_gelten_als_zeit_auskunft():
    for satz in LIVE:
        assert zeiten_wache.ist_zeit_auskunft(satz), satz


def test_weitere_formulierungen_werden_erkannt():
    for satz in [
        "Unsere Öffnungszeiten sind montags bis freitags von 8 bis 18 Uhr.",
        "Freitags haben wir bis 14 Uhr geöffnet.",
        "Am Mittwoch ist die Praxis nachmittags geschlossen.",
        "Sie erreichen uns montags bis donnerstags ab 8 Uhr.",
        "Wir haben dienstags offen.",
        "Die Sprechzeiten sind vormittags von 8 bis 12 Uhr.",
    ]:
        assert zeiten_wache.ist_zeit_auskunft(satz), satz


# --- Gegenproben: das Wichtigere -------------------------------------------
def test_termin_saetze_mit_uhrzeit_bleiben_unangetastet():
    """Kalender-Aussagen haben ihre eigene Wache (W-FAKTEN-WACHE, Slot-Claim)
    — hier darf nichts fallen, sonst verliert die Buchung ihr Angebot."""
    for satz in [
        "Am Montag um neun Uhr hätte ich einen Termin frei.",
        "Ich habe am Freitag um 14 Uhr noch einen Platz.",
        "Dann halte ich Dienstag, den sechzehnten September um zehn Uhr fest.",
        "Ihr Termin ist am Donnerstag um elf Uhr dreißig.",
        "Passt Ihnen morgens um acht Uhr, oder lieber nachmittags?",
        "Soll ich den Termin am Freitag um 9 Uhr absagen?",
    ]:
        assert not zeiten_wache.ist_zeit_auskunft(satz), satz


def test_saetze_ohne_zeitangabe_bleiben():
    for satz in [
        "Wir sind eine Hautarztpraxis.",
        "Die Praxis ist gut mit der Bahn zu erreichen.",
        "Gerne bin ich für Sie da.",
        "Die genauen Öffnungszeiten erfragen Sie am besten direkt in der Praxis.",
    ]:
        assert not zeiten_wache.ist_zeit_auskunft(satz), satz


def test_belegte_praxis_spricht_ihre_zeiten_weiter_aus():
    """Die Kern-Gegenprobe: bei MedDent bleibt jede Zeit-Auskunft stehen."""
    t = laden("meddent")
    t["dbPrompt"] = "- Öffnungszeiten: Mo - Do: 08:00 - 18:00 Uhr, Fr: 08:00 - 16:00 Uhr"
    for satz in LIVE:
        neu, weg = zeiten_wache.saeubern(_sit(t), satz)
        assert weg == [] and neu == satz


# --- Saeubern ---------------------------------------------------------------
def test_erfundene_zeiten_fallen_und_der_rest_bleibt():
    sit = _sit(_ruether())
    neu, weg = zeiten_wache.saeubern(
        sit, "Wir sind freitags von 8 bis 12 Uhr für Sie da. Wie ist Ihr Nachname?")
    assert len(weg) == 1
    assert "8 bis 12" not in neu
    assert "Wie ist Ihr Nachname?" in neu


def test_bleibt_nichts_kommt_die_ehrliche_auskunft():
    sit = _sit(_ruether())
    neu, weg = zeiten_wache.saeubern(sit, LIVE[1])
    assert weg == [LIVE[1]]
    assert neu == zeiten_wache.ERSATZ
    assert "nicht vorliegen" in neu


def test_ersatz_verspricht_nichts_und_stellt_keine_frage():
    """Der Ersatz darf die Fakten-Wache nicht neu triggern (keine Zeit, kein
    Slot) und das Frage-Gate nicht (keine Datenfrage)."""
    assert "?" not in zeiten_wache.ERSATZ
    assert not zeiten_wache.ist_zeit_auskunft(zeiten_wache.ERSATZ)


# --- Stufen / Notaus --------------------------------------------------------
def test_default_ist_enforce_und_notaus_greift(monkeypatch):
    monkeypatch.delenv("ZEITEN_WACHE", raising=False)
    assert zeiten_wache.modus() == "enforce"
    monkeypatch.setenv("ZEITEN_WACHE", "shadow")
    assert zeiten_wache.modus() == "shadow"
    monkeypatch.setenv("ZEITEN_WACHE", "0")
    assert zeiten_wache.modus() == "off"


# --- Ende zu Ende im Agenten (ohne Modell) ---------------------------------
def test_agent_streicht_die_erfindung_am_zugende(monkeypatch):
    from bianca import agent as bagent
    sit = _sit(_ruether())
    monkeypatch.setenv("ZEITEN_WACHE", "enforce")
    raus = bagent._zeiten_wache_anwenden(sit, LIVE[0])
    assert raus == zeiten_wache.ERSATZ
    assert any(e.get("w") == "zeiten-wache" for e in sit.get("_spur", []))


def test_agent_shadow_aendert_nichts(monkeypatch):
    from bianca import agent as bagent
    sit = _sit(_ruether())
    monkeypatch.setenv("ZEITEN_WACHE", "shadow")
    assert bagent._zeiten_wache_anwenden(sit, LIVE[0]) == LIVE[0]


# --- Die Frage selbst erkennen (deterministischer Weg statt Modell) --------
def test_offenfragen_ohne_wann_erreichen_den_deterministischen_weg():
    from kern.wissen import auskunft_themen
    for frage in [
        "Wann habt ihr auf?",
        "Haben Sie am Freitag offen?",
        "Ist die Praxis morgen geöffnet?",
        "Wann machen Sie auf?",
        "Wann haben Sie geöffnet?",
        "Wie sind Ihre Sprechzeiten?",
    ]:
        assert "oeffnungszeiten" in auskunft_themen(frage), frage


def test_terminfragen_gelten_nicht_als_zeitenfrage():
    from kern.wissen import auskunft_themen
    for frage in [
        "Haben Sie den Termin noch offen?",
        "Ist noch etwas offen bei mir?",
        "Ich warte auf den Termin.",
        "Haben Sie einen Platz frei?",
        "Wann ist mein Termin?",
    ]:
        assert "oeffnungszeiten" not in auskunft_themen(frage), frage
