"""W-MENUE-ANTWORT (05.10.2026): Blessing-Anrufer antworteten auf „Geht es
um einen Termin, eine Absage, eine Verschiebung oder eine Terminauskunft?“
mit „Camin!“, „Jamin. Ja.“, „Einen neuen Termin!“, „Terminauskunst.“ oder
„Rominauskunft.“ — und bekamen bis zu sechsmal dasselbe Menü zurück."""

from __future__ import annotations

import pytest

from bianca import agent, gehirn, session
from kern import gespraech
from kern.tenants import laden


@pytest.fixture(autouse=True)
def _ohne_llm(monkeypatch):
    monkeypatch.setenv("INTENT_NACHZUG", "0")

    def _kein_llm(*a, **k):
        raise AssertionError("Menü-Antwort darf nicht ans freie LLM")

    monkeypatch.setattr(agent.llm, "chat", _kein_llm)
    monkeypatch.setattr(agent.llm, "chat_stream", _kein_llm)
    monkeypatch.setattr(agent.flow.hintergrund, "anstossen", lambda sit: None)


def _nach_menue(tenant_id: str = "blessing") -> dict:
    sit = session.neu(tenant=laden(tenant_id))
    agent.start_reply(sit)
    sit["messages"].append({"role": "assistant",
                            "content": f"Verstehe. {gespraech.KOMPAKT_JOBFRAGE}"})
    return sit


@pytest.mark.parametrize("gesagt", ["Camin!", "Jamin!", "Einen neuen Termin!", "Termin!"])
def test_termin_auf_das_menue_startet_die_buchung(gesagt):
    sit = _nach_menue()
    aus = agent.user_turn(sit, gesagt)
    assert gespraech.KOMPAKT_JOBFRAGE not in aus["text"]
    assert gehirn.sammler(sit).get("modus") == "buchen"


@pytest.mark.parametrize("gesagt", ["Terminauskunst.", "Rominauskunft."])
def test_auskunft_auf_das_menue_startet_die_auskunft(gesagt):
    sit = _nach_menue()
    aus = agent.user_turn(sit, gesagt)
    assert gespraech.KOMPAKT_JOBFRAGE not in aus["text"]
    assert gehirn.sammler(sit).get("modus") == "auskunft"


def test_verschieden_heisst_verschieben():
    sit = _nach_menue()
    agent.user_turn(sit, "Verschieden.")
    assert gehirn.sammler(sit).get("modus") == "verschieben"


def test_untermenue_zweimal_unklar_wird_neubuchung():
    sit = session.neu(tenant=laden("blessing"))
    agent.start_reply(sit)
    erst = agent.user_turn(sit, "Termin!")
    assert agent.TERMIN_EINWORT_FRAGE in erst["text"]
    zweit = agent.user_turn(sit, "Jamin. Ja.")
    assert agent.TERMIN_EINWORT_NACHFRAGE in zweit["text"]
    agent.user_turn(sit, "Jamin!")
    assert gehirn.sammler(sit).get("modus") == "buchen"


def test_menue_wahl_gegenproben():
    # Zwei verschiedene Aufträge in einem Satz sind keine Menü-Wahl.
    assert agent._menue_wahl("Absagen oder verschieben", termin_heisst_neu=True) == ""
    # Lange Sätze gehören der normalen Erkennung.
    assert agent._menue_wahl(
        "Ich wollte eigentlich nur fragen ob das mit dem Termin so passt",
        termin_heisst_neu=True) == ""
    # „Vitamin“ ist kein Termin-Hörfehler dieser Regel.
    assert agent._menue_wahl("Vitamin", termin_heisst_neu=True) == ""
    assert agent._menue_wahl("Beratung.", termin_heisst_neu=True) == ""
