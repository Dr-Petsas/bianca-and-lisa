"""Paket 7: Anliegen-Menue und „Sonst noch?" schleifenfrei.

Replays ``blessing-auskunft-menue`` (das Menue-Wort „Auskunft"/
„Terminauskunft" wurde nicht als Antwort erkannt, Menue loopte 6x) und
``blessing-sonst-noch" (schliessende Floskel fiel durch und loopte).
"""
from __future__ import annotations

import pytest

from bianca import agent, flow, gehirn, session
from kern import gespraech, intent
from kern.tenants import laden
from tests.live_replays import replay


@pytest.fixture(autouse=True)
def _ohne_nachzug(monkeypatch):
    monkeypatch.setenv("INTENT_NACHZUG", "0")
    monkeypatch.setenv("INTENT_SCHICHT", "1")


def _kein_llm(monkeypatch):
    for fn in ("chat", "chat_stream"):
        monkeypatch.setattr(
            agent.llm, fn,
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("Menue-Antwort darf nicht ans freie LLM")),
        )


# --- Replay blessing-auskunft-menue -----------------------------------------

@pytest.mark.parametrize("gesagt", ["Auskunft.", "Terminauskunft", "Ja, Auskunft."])
def test_intent_erkennt_menue_auskunft(gesagt):
    sit = {"tenant": laden("blessing"), "sammler": {},
           "hirn": {"anliegen": [], "aktiv": ""}}
    d = intent.erkennen(sit, gesagt)
    assert d.get("handlung") == "WISSEN"
    assert d.get("gegenstand") == "VORGANG"


@pytest.mark.parametrize("gesagt", ["Auskunft.", "Terminauskunft", "Ja, Auskunft."])
def test_menueantwort_fuehrt_in_auskunft_ohne_loop(gesagt, monkeypatch):
    _kein_llm(monkeypatch)
    sit = session.neu(tenant=laden("blessing"))
    agent.start_reply(sit)
    aus = agent.user_turn(sit, gesagt)
    assert gespraech.KOMPAKT_JOBFRAGE not in aus.get("text", "")
    assert gehirn.sammler(sit).get("modus") == "auskunft"


def test_replay_auskunft_menue_metadaten():
    r = replay("blessing-auskunft-menue")
    assert r.tenant == "blessing"
    assert r.klasse == "auskunft_menue_schleife"


def test_echter_terminwunsch_bleibt_buchung():
    """Gegenprobe: „einen Termin" ist keine Auskunft."""
    sit = {"tenant": laden("blessing"), "sammler": {},
           "hirn": {"anliegen": [], "aktiv": ""}}
    d = intent.erkennen(sit, "Ich hätte gern einen Termin.")
    assert d.get("handlung") == "ANLEGEN"


# --- Replay blessing-sonst-noch ---------------------------------------------

@pytest.mark.parametrize("gesagt", [
    "Okay, passt schon.",
    "Alles klar.",
    "Passt.",
    "Das reicht.",
    "Ja, passt so, danke.",
])
def test_sonst_noch_schliessende_floskel_legt_auf(gesagt):
    sit = {"tenant": {}, "sammler": {"frage": "sonst_noch"}}
    aus = flow._sonst_noch_antwort(
        sit, gesagt, ja_text="JA", nein_text="Sehr gerne. Auf Wiederhören.")
    assert aus is not None
    assert aus.get("hangup")


def test_sonst_noch_folgeanliegen_faellt_nicht_auf():
    """Gegenprobe: ein echtes Folge-Anliegen ist keine Schluss-Floskel."""
    assert flow._SONST_NOCH_FERTIG_RE.match("Ja, ich bräuchte noch einen Termin.") is None
    assert flow._SONST_NOCH_FERTIG_RE.match("Ja, passt, aber ich habe noch eine Frage.") is None


def test_sonst_noch_kein_slot_dispatch_legt_auf(monkeypatch):
    _kein_llm(monkeypatch)
    sit = session.neu(tenant=laden("blessing"))
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["phase"] = "fertig"
    s["frage"] = "sonst_noch"
    sit["keinSlotFertig"] = True
    sit["sonstNochGefragt"] = True
    aus = flow.zug(sit, "Okay, passt schon.", lambda *a, **k: None)
    assert aus is not None and aus.get("hangup")


def test_replay_sonst_noch_metadaten():
    r = replay("blessing-sonst-noch")
    assert r.tenant == "blessing"
    assert r.klasse == "sonst_noch_schleife"
