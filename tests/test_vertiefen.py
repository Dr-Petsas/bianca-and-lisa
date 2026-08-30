"""Auftrag vertiefen: Einzeiler bekommen Gesprächsschichten, kein Gedächtnis-Müll."""

from __future__ import annotations

from lisa import vertiefen
from lisa.prompt import system_prompt


def test_notfall_vertiefen_recall_hat_begruendung_und_schichten():
    text = vertiefen.notfall_vertiefen("Recall vereinbaren")
    assert "Recall vereinbaren" in text
    assert "Begründung" in text
    assert "Gesprächsschichten" in text
    assert "nicht vorlesen" in text.lower() or "Regie" in text


def test_vertiefen_ohne_auftrag_scheitert():
    out = vertiefen.vertiefen("  ")
    assert not out["ok"] and out["auftrag"] == ""


def test_vertiefen_ohne_llm_schreibt_trotzdem():
    echt = vertiefen._llm_vertiefen
    vertiefen._llm_vertiefen = lambda *a, **k: ""
    echt_g = vertiefen._gedaechtnis_zu
    vertiefen._gedaechtnis_zu = lambda n, p: ("", "nichts")
    try:
        out = vertiefen.vertiefen("Recall nächste Woche")
        assert out["ok"] and "Recall nächste Woche" in out["auftrag"]
        assert "Gesprächsschichten" in out["auftrag"]
        assert out["gedaechtnis"] == "nichts" and not out["hatStand"]
    finally:
        vertiefen._llm_vertiefen = echt
        vertiefen._gedaechtnis_zu = echt_g


def test_lisa_prompt_fordert_gespraechstiefe():
    p = system_prompt(praxis="Testpraxis", behandler="Dr. T",
                      auftrag="Recall", patient="Anna Test")
    assert "GESPRÄCHSTIEFE" in p
    assert "nach Zug 2 nicht aufhören" in p
