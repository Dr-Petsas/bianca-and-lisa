"""W-RUHE (15.09.2026): gemeinsame Ein-Frage-/Ein-Thema-Ausgangswache.

Die Gegenproben (nichts anfassen, wenn ein Fakt hinter der Frage haengt) sind
der wichtigere Teil — ein blind weggeschnittener Alternativ-Slot oder ein
Sicherheitshinweis waere der teurere Fehler.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kern import gespraechsruhe  # noqa: E402


def test_streicht_nachgeplauder_hinter_der_frage():
    neu, weg = gespraechsruhe.saeubern(
        "Gerne. Wie ist Ihr Nachname? Kann ich sonst noch etwas für Sie tun?"
    )
    assert neu == "Gerne. Wie ist Ihr Nachname?"
    assert weg == ["Kann ich sonst noch etwas für Sie tun?"]


def test_zweite_frage_faellt():
    neu, weg = gespraechsruhe.saeubern(
        "Waren Sie schon einmal bei uns? Und wie heißen Sie?"
    )
    assert neu == "Waren Sie schon einmal bei uns?"
    assert len(weg) == 1


def test_frage_am_ende_bleibt():
    text = "Alles klar. Ich habe Ihren Wunsch notiert. Wie ist Ihr Nachname?"
    neu, weg = gespraechsruhe.saeubern(text)
    assert weg == []
    assert neu == text


def test_reine_aussage_bleibt():
    text = "Erledigt — der Termin ist abgesagt. Ich schicke Ihnen die SMS."
    neu, weg = gespraechsruhe.saeubern(text)
    assert weg == []


def test_fakt_hinter_frage_bleibt_komplett():
    """Angebotener Alternativ-Slot hinter einer Frage darf nie wegfallen."""
    text = ("Passt Ihnen der Donnerstag? Frei wäre auch Freitag um "
            "vierzehn Uhr.")
    neu, weg = gespraechsruhe.saeubern(text)
    assert weg == []
    assert neu == text


def test_sicherheitshinweis_hinter_frage_bleibt():
    text = ("Soll ich einen Termin machen? Bei akuter Atemnot rufen Sie "
            "bitte die 112.")
    neu, weg = gespraechsruhe.saeubern(text)
    assert weg == []


def test_notaus_off(monkeypatch):
    monkeypatch.setenv("RUHE_WACHE", "off")
    assert gespraechsruhe.modus() == "off"
    monkeypatch.setenv("RUHE_WACHE", "shadow")
    assert gespraechsruhe.modus() == "shadow"
    monkeypatch.delenv("RUHE_WACHE", raising=False)
    assert gespraechsruhe.modus() == "enforce"
