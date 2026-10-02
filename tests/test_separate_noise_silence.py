"""Paket 8: Diktat-Pause ist ein stiller warte-Zug, kein Presence-Stups.

Replay ``blessing-presence-diktat``: „Sind Sie noch dran?" feuerte, während
der Anrufer noch buchstabierte. Ein offenes Buchstabier-/Nummern-Teilstück
hält die Leitung still, ohne den Anrufer zu unterbrechen.
"""
from __future__ import annotations

import pytest

from bianca import agent, gehirn, session
from kern.tenants import laden
from tests.live_replays import replay


@pytest.fixture(autouse=True)
def _ohne_nachzug(monkeypatch):
    monkeypatch.setenv("INTENT_NACHZUG", "0")


def _sit():
    sit = session.neu(tenant=laden("blessing"))
    agent.start_reply(sit)
    return sit


def test_buchstabier_teilstueck_ist_stiller_warte_zug():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["frage"] = "buchstabieren"
    s["buchstabenTeil"] = "GRAF"
    aus = agent.stille_zug(sit)
    assert aus.get("text") == ""          # kein Ton
    assert aus.get("warte") is True
    assert "Sind Sie noch dran" not in (aus.get("text") or "")


def test_nummern_teilstueck_ist_stiller_warte_zug():
    sit = _sit()
    s = gehirn.sammler(sit)
    s["frage"] = "telefon"
    s["telefonTeil"] = "01511"
    aus = agent.stille_zug(sit)
    assert aus.get("text") == ""
    assert aus.get("warte") is True


def test_ohne_teilstueck_kommt_normale_presence():
    """Gegenprobe: ohne offenes Diktat-Fragment stupst Bianca wie bisher."""
    sit = _sit()
    gehirn.sammler(sit)["frage"] = "nachname"
    aus = agent.stille_zug(sit)
    assert "Sind Sie noch dran" in (aus.get("text") or "")


def test_diktat_hold_unterbricht_den_anrufer_nicht():
    """Waehrend ein Teilstueck offen liegt, kommt NIE ein Presence-Satz —
    auch nicht beim zweiten stillen Poll (der Anrufer buchstabiert weiter).
    Ein wirklich totes Gespraech endet weiterhin ueber die Call-Death-Deckel;
    das ist NICHT Teil dieser Garantie."""
    sit = _sit()
    s = gehirn.sammler(sit)
    s["frage"] = "buchstabieren"
    s["buchstabenTeil"] = "GRAF"
    aus1 = agent.stille_zug(sit)
    aus2 = agent.stille_zug(sit)
    assert aus1.get("text") == "" and aus1.get("warte") is True
    assert "Sind Sie noch dran" not in (aus2.get("text") or "")


def test_replay_presence_diktat_metadaten():
    r = replay("blessing-presence-diktat")
    assert r.tenant == "blessing"
    assert r.klasse == "presence_im_diktat"
