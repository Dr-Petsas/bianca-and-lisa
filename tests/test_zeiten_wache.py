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


def test_auf_die_frage_kommt_die_auskunft_zuerst():
    """Live blieb nach dem Streichen nur „Möchten Sie sich zur Kontrolle
    vorstellen?" übrig — eine Rückfrage, die an der gestellten Frage
    vorbeigeht. Auf eine Zeiten-Frage steht die ehrliche Auskunft VORN."""
    sit = _sit(_ruether())
    neu, weg = zeiten_wache.saeubern(
        sit,
        "Ja, wir sind freitags von 8 bis 12 Uhr für Sie da. "
        "Möchten Sie sich zur Kontrolle vorstellen?",
        gefragt="Haben Sie am Freitag offen?",
    )
    assert len(weg) == 1
    assert neu.startswith(zeiten_wache.ERSATZ)
    assert "Möchten Sie sich zur Kontrolle vorstellen?" in neu
    assert "8 bis 12" not in neu


def test_ohne_frage_bleibt_der_rest_ohne_vorsatz():
    """Fing das Modell von selbst mit Zeiten an, genügt das Streichen — der
    Ersatz würde eine Auskunft aufdrängen, die niemand wollte."""
    sit = _sit(_ruether())
    neu, _ = zeiten_wache.saeubern(
        sit, "Wir sind freitags von 8 bis 12 Uhr für Sie da. Wie ist Ihr Nachname?",
        gefragt="Ich hätte gern einen Termin.")
    assert neu == "Wie ist Ihr Nachname?"


def test_ersatz_kommt_pro_zug_nur_einmal():
    """P5-Strom: jeder Satz läuft einzeln durch die Wache. Zwei erfundene
    Zeit-Sätze hätten die ehrliche Auskunft sonst zweimal gesprochen; der
    zweite Satz fällt dann ersatzlos — nie die Erfindung als Rückfall."""
    sit = _sit(_ruether())
    frage = "Wann haben Sie geöffnet?"
    erst, weg1 = zeiten_wache.saeubern(sit, LIVE[0], gefragt=frage)
    zweit, weg2 = zeiten_wache.saeubern(sit, LIVE[2], gefragt=frage)
    assert erst == zeiten_wache.ERSATZ and weg1 == [LIVE[0]]
    assert zweit == "" and weg2 == [LIVE[2]]


def test_naechster_zug_darf_wieder_antworten():
    """Fragt der Anrufer erneut, ist der Riegel neu — sonst bliebe die
    zweite Frage unbeantwortet."""
    from kern import qwen_korrektor
    sit = _sit(_ruether())
    qwen_korrektor.naechster_zug(sit)
    eins, _ = zeiten_wache.saeubern(sit, LIVE[0], gefragt="Wann haben Sie auf?")
    qwen_korrektor.naechster_zug(sit)
    zwei, _ = zeiten_wache.saeubern(sit, LIVE[2], gefragt="Und am Freitag?")
    assert eins == zeiten_wache.ERSATZ and zwei == zeiten_wache.ERSATZ


def test_shadow_verbraucht_den_ersatz_nicht():
    sit = _sit(_ruether())
    zeiten_wache.saeubern(sit, LIVE[0], gefragt="Wann haben Sie auf?",
                          merken=False)
    neu, _ = zeiten_wache.saeubern(sit, LIVE[0], gefragt="Wann haben Sie auf?")
    assert neu == zeiten_wache.ERSATZ


# --- Fortsetzung des gestrichenen Zeitplans --------------------------------
def test_rueckbezug_faellt_mit(monkeypatch):
    """Live-Rest vom 15.09.2026: hinter der ehrlichen Auskunft blieb „Danach
    schließen wir." stehen — ein Rückbezug auf einen Satz, den es nicht mehr
    gibt."""
    sit = _sit(_ruether())
    neu, weg = zeiten_wache.saeubern(
        sit, "Wir sind heute bis 12 Uhr für Sie da. Danach schließen wir. "
             "Möchten Sie einen Termin?",
        gefragt="Wann haben Sie geöffnet?")
    assert len(weg) == 2
    assert "Danach" not in neu and "schließen" not in neu
    assert "Möchten Sie einen Termin?" in neu


def test_rueckbezug_faellt_auch_im_naechsten_p5_satz():
    """Im P5-Strom läuft jeder Satz einzeln — der Rückbezug kommt in einem
    eigenen Aufruf und muss trotzdem fallen."""
    sit = _sit(_ruether())
    frage = "Wann haben Sie geöffnet?"
    zeiten_wache.saeubern(sit, LIVE[0], gefragt=frage)
    neu, weg = zeiten_wache.saeubern(sit, "Danach schließen wir.", gefragt=frage)
    assert weg == ["Danach schließen wir."] and neu == ""


def test_rueckbezug_allein_bleibt_unangetastet():
    """Ohne gestrichenen Vorgänger wird nichts gestrichen — sonst fiele ein
    harmloser Satz mitten im Gespräch."""
    sit = _sit(_ruether())
    neu, weg = zeiten_wache.saeubern(sit, "Danach schließen wir.")
    assert weg == [] and neu == "Danach schließen wir."


def test_rueckbezug_mit_termin_bezug_bleibt():
    sit = _sit(_ruether())
    neu, weg = zeiten_wache.saeubern(
        sit, "Wir sind heute bis 12 Uhr für Sie da. "
             "Danach hätte ich noch einen Termin frei.",
        gefragt="Wann haben Sie geöffnet?")
    assert len(weg) == 1
    assert "Danach hätte ich noch einen Termin frei." in neu


def test_sonst_noch_etwas_ist_kein_rueckbezug():
    """„Gibt es sonst noch etwas …?" trägt „sonst", aber keine Zeit und kein
    Schließen — die Abschlussfrage darf nie fallen."""
    sit = _sit(_ruether())
    neu, _ = zeiten_wache.saeubern(
        sit, "Wir sind heute bis 12 Uhr für Sie da. "
             "Gibt es sonst noch etwas, das ich für Sie tun kann?",
        gefragt="Wann haben Sie geöffnet?")
    assert "Gibt es sonst noch etwas, das ich für Sie tun kann?" in neu


# --- Auf die Frage genügt die Zeitangabe (streng) ---------------------------
def test_knappe_antwort_ohne_oeffnungswort_faellt_auf_die_frage():
    """„Heute von 8 bis 12 Uhr und von 14 bis 16 Uhr." trägt kein
    Öffnungs-Vokabular — auf die Zeiten-Frage ist es trotzdem die Antwort."""
    sit = _sit(_ruether())
    neu, weg = zeiten_wache.saeubern(
        sit, "Heute von 8 bis 12 Uhr und von 14 bis 16 Uhr.",
        gefragt="Wann haben Sie geöffnet?")
    assert weg and neu == zeiten_wache.ERSATZ


def test_ohne_zeitenfrage_bleibt_eine_blanke_uhrzeit_stehen():
    """Ohne gestellte Zeiten-Frage bleibt die strenge Regel aus — sonst fiele
    jeder Satz mit einer Uhrzeit."""
    sit = _sit(_ruether())
    neu, weg = zeiten_wache.saeubern(
        sit, "Dann sehen wir uns um 14 Uhr.", gefragt="Passt 14 Uhr?")
    assert weg == [] and neu == "Dann sehen wir uns um 14 Uhr."


def test_termin_saetze_fallen_auch_auf_die_zeitenfrage_nicht():
    """Die teurere Richtung: auf „Haben Sie am Freitag offen?" darf das
    Slot-Angebot nicht mitfallen."""
    sit = _sit(_ruether())
    neu, weg = zeiten_wache.saeubern(
        sit, "Am Freitag um 9 Uhr hätte ich einen Termin frei. "
             "Möchten Sie sich für einen Termin vormittags anmelden?",
        gefragt="Haben Sie am Freitag offen?")
    assert weg == []
    assert neu.startswith("Am Freitag um 9 Uhr")


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


def test_agent_gibt_nie_die_erfindung_zurueck(monkeypatch):
    """Der zweite erfundene Satz eines Zugs (P5) kommt ersatzlos — aber
    `neu or text` haette dort die Erfindung zurueckgegeben."""
    from bianca import agent as bagent
    sit = _sit(_ruether())
    monkeypatch.setenv("ZEITEN_WACHE", "enforce")
    frage = "Wann haben Sie geöffnet?"
    assert bagent._zeiten_wache_anwenden(sit, LIVE[0], frage) == zeiten_wache.ERSATZ
    assert bagent._zeiten_wache_anwenden(sit, LIVE[2], frage) == ""


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
