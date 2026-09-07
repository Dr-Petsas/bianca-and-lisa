"""Nacktes Motiv (Chef 07.09.2026): 'Zahnreinigung' startet keine Buchung.

Live 06.09.: der Anrufer sagte nur das Wort — Bianca antwortete
'Das habe ich nicht verstanden.' Soll: Motiv merken und nachfragen
'Brauchen Sie einen Termin zur Zahnreinigung?' — Ja oeffnet die
Buchung mit schon gesetztem Grund, Nein nicht.
"""

from bianca import agent, flow, gehirn
from kern import gespraech, hirn, llm
from kern.tenants import laden


def _sit() -> dict:
    sit = {
        "stimme": "Bianca",
        "tenant": laden("meddent"),
        "messages": [
            {"role": "system", "content": "x"},
            {"role": "assistant", "content": "Guten Tag, hier ist Bianca."},
        ],
    }
    hirn.init(sit)
    return sit


def _ohne_llm(fn):
    def _knall(*a, **k):
        raise AssertionError("LLM darf auf nacktes Motiv nicht laufen")

    echt_chat, echt_stream = llm.chat, llm.chat_stream
    llm.chat = _knall
    llm.chat_stream = _knall
    try:
        return fn()
    finally:
        llm.chat = echt_chat
        llm.chat_stream = echt_stream


def test_zahnreinigung_fragt_nach_termin_startet_nicht():
    """Live-Satz wortgleich: allein 'Zahnreinigung'."""
    def _lauf():
        sit = _sit()
        aus = agent.user_turn(sit, "Zahnreinigung")
        s = sit["sammler"]
        assert gespraech.UNKLAR_ANTWORT not in (aus.get("text") or "")
        assert "Termin" in aus["text"]
        assert "Zahnreinigung" in aus["text"]
        assert s["modus"] != "buchen"
        assert s["frage"] == "termin_anbieten"
        assert gehirn.ist_pzr_grund(s)
        assert "zahnreinigung" in (s.get("grund") or "").lower()
        return sit

    sit = _ohne_llm(_lauf)
    assert sit["sammler"]["terminAnbieten"] == "gefragt"


def test_zahnreinigung_ja_startet_buchung_mit_grund():
    def _lauf():
        sit = _sit()
        agent.user_turn(sit, "Zahnreinigung")
        aus = agent.user_turn(sit, "Ja")
        s = sit["sammler"]
        assert s["modus"] == "buchen"
        assert s["frage"] == "schonmal"
        assert gehirn.ist_pzr_grund(s)
        assert "schon" in aus["text"].lower()
        assert "worum geht" not in aus["text"].lower()
        return sit

    _ohne_llm(_lauf)


def test_zahnreinigung_nein_bucht_nicht():
    def _lauf():
        sit = _sit()
        agent.user_turn(sit, "Zahnreinigung")
        aus = agent.user_turn(sit, "Nein")
        s = sit["sammler"]
        assert s["modus"] != "buchen"
        assert s["terminAnbieten"] == "nein"
        assert "sonst" in aus["text"].lower()
        return sit

    _ohne_llm(_lauf)


def test_ich_brauche_zahnreinigung_ist_kein_nacktes_motiv():
    """Ausdrücklicher Wunsch bleibt Buchung — nur das nackte Wort fragt nach."""
    assert not gehirn.ist_nacktes_pzr("Ich brauche eine Zahnreinigung")
    assert gehirn.ist_terminwunsch("Ich brauche eine Zahnreinigung")
    z = flow.zug(_sit(), "Ich brauche eine Zahnreinigung.")
    # Mit Hirn setzt Intent ANLEGEN nicht (kein 'Termin'-Wort) — der Satz
    # ist trotzdem kein nacktes Motiv, also keine Nachfrage-Frage.
    if z is not None:
        assert z.get("text")
        assert "Brauchen Sie einen Termin zur Zahnreinigung" not in (z.get("text") or "")


def test_intent_aus_nacktes_pzr_setzt_trotzdem_keinen_modus():
    """Ohne Intent-Schicht darf _TERMIN_RE das Wort nicht zur Buchung machen."""
    sit = _sit()
    sit.pop("hirn", None)
    neu = gehirn.einsammeln(sit, "Zahnreinigung")
    s = sit["sammler"]
    assert "modus" not in neu
    assert s["modus"] == ""
    assert gehirn.ist_pzr_grund(s)
