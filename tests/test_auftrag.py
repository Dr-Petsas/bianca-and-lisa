"""Offline-Tests fuer den Teststudio-Auftrag nach einem Einzellauf."""

from __future__ import annotations

import tempfile
from pathlib import Path

from tests.baukasten import auftrag


def _bericht(**kw):
    b = {
        "id": "s01-markus-kontrolle",
        "story": {"id": "s01-markus-kontrolle", "stimme": "markus",
                  "vorname": "Martin", "nachname": "Berger",
                  "anliegen": "termin", "grund": "kontrolle",
                  "eroeffnungText": "Hallo, ich brauche einen Termin."},
        "fehler": "",
        "zuege": [
            {"wer": "bianca", "text": "Guten Tag, hier ist Bianca.", "frage": "schonmal"},
            {"wer": "anrufer", "text": "Nein, das erste Mal.", "gehoert": "Nein, das erste Mal.",
             "baustein": "schonmal"},
        ],
        "ergebnis": {"ok": True, "checks": [{"name": "kein Fehler", "ok": True}],
                     "latenzMaxS": 1.1, "ersterTonMaxS": 0.8, "waechter": []},
    }
    b.update(kw)
    return b


def test_stt_abweichung_wird_ticket():
    b = _bericht(zuege=[
        {"wer": "anrufer", "text": "Ich heiße Martin Berger.",
         "gehoert": "Ich heiße Martin Berger Möbel.", "baustein": "name"},
    ])
    tickets = auftrag.tickets_aus_bericht(b)
    assert any(t["art"] == "stt" and "Möbel" in t["text"] for t in tickets)


def test_roter_check_wird_ticket():
    b = _bericht(ergebnis={
        "ok": False,
        "checks": [{"name": "Nachname", "ok": False, "soll": "Berger", "ist": "Möbel"}],
        "latenzMaxS": 1.0, "ersterTonMaxS": 0.4, "waechter": [],
    })
    tickets = auftrag.tickets_aus_bericht(b)
    assert any(t["art"] == "check" and "Nachname" in t["titel"] for t in tickets)


def test_lauf_fehler_wird_ticket():
    tickets = auftrag.tickets_aus_bericht(auftrag.ersatz(
        {"id": "s01-x"}, "Freifeld-Audio vor dem Start fehlgeschlagen"))
    assert tickets[0]["art"] == "fehler"


def test_gruen_ohne_automatische_tickets():
    assert auftrag.tickets_aus_bericht(_bericht()) == []


def test_schreiben_und_hinweis(tmp_path=None):
    ordner = Path(tempfile.mkdtemp()) if tmp_path is None else Path(tmp_path)
    paket = auftrag.schreiben(_bericht(), "20260830-021000", ordner=ordner)
    assert paket["chatSatz"] == "Übergabe"
    assert "Hallo, ich brauche einen Termin." in paket["storyKurz"]
    assert (ordner / "aktuell.md").is_file()
    assert (ordner / "vorschlag.md").is_file()
    assert list((ordner / "archiv").glob("*.md"))
    gelesen = auftrag.lesen(ordner)
    assert gelesen["laufId"] == "20260830-021000"
    neu = auftrag.hinweis_setzen("Namen nachfragen, nicht raten.", ordner=ordner)
    assert "Namen nachfragen" in neu["markdown"]
    assert "Übergabe" in neu["markdown"]
    assert "Namen nachfragen" in (ordner / "vorschlag.md").read_text(encoding="utf-8")


def test_marke_landet_im_markdown(tmp_path=None):
    from pathlib import Path
    import tempfile
    ordner = Path(tempfile.mkdtemp()) if tmp_path is None else Path(tmp_path)
    auftrag.schreiben(_bericht(), "20260830-045500", ordner=ordner)
    neu = auftrag.marken_setzen([{
        "idx": 0, "wer": "Bianca",
        "text": "Guten Tag, hier ist Bianca.",
        "kommentar": "verkauft nur die drei Slots, sucht nicht später",
    }], ordner=ordner)
    assert "Markierte Antworten" in neu["markdown"]
    assert "sucht nicht später" in neu["markdown"]
    assert "Zug 0" in neu["markdown"]
