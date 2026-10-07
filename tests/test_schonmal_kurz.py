"""W-SCHONMAL-KURZ (07.10.2026, Anruf c5870cde): „Ich war schon.“ ist Bestand."""

import pytest

from bianca import gehirn
from kern.tenants import laden


def _sit(frage: str = "schonmal") -> dict:
    sit = {"tenant": laden("meddent"), "messages": []}
    s = gehirn.sammler(sit)
    s["modus"] = "buchen"
    s["frage"] = frage
    return sit


@pytest.mark.parametrize("satz", [
    "Ich war schon.",
    "War schon mal.",
    "Ja, ich war schon einmal.",
    "Wir waren bereits.",
    "Ich bin schon öfter.",
])
def test_kurzantwort_auf_schonmal_ist_bestand(satz):
    sit = _sit()
    gehirn.einsammeln(sit, satz)
    assert gehirn.sammler(sit)["warSchonMal"] is True, satz


@pytest.mark.parametrize("satz", [
    "Ich war schon beim Hausarzt.",
    "Ich war schon unterwegs.",
])
def test_anderer_inhalt_bleibt_offen(satz):
    sit = _sit()
    gehirn.einsammeln(sit, satz)
    assert gehirn.sammler(sit)["warSchonMal"] is None, satz


def test_nein_und_doppelverneinung_unveraendert():
    sit = _sit()
    gehirn.einsammeln(sit, "Nein, das erste Mal.")
    assert gehirn.sammler(sit)["warSchonMal"] is False
    sit = _sit()
    gehirn.einsammeln(sit, "Nein, noch nicht das erste Mal.")
    assert gehirn.sammler(sit)["warSchonMal"] is True


def test_ausserhalb_der_schonmal_frage_keine_wirkung():
    sit = _sit(frage="grund")
    gehirn.einsammeln(sit, "Ich war schon.")
    assert gehirn.sammler(sit)["warSchonMal"] is None


def test_notaus(monkeypatch):
    monkeypatch.setenv("SCHONMAL_KURZ", "0")
    sit = _sit()
    gehirn.einsammeln(sit, "Ich war schon.")
    assert gehirn.sammler(sit)["warSchonMal"] is None
