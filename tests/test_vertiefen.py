"""Auftrag vorbereiten: Chef-Text bleibt, Gesprächsplan nur aus Belegtem."""

from __future__ import annotations

from lisa import vertiefen
from lisa.prompt import system_prompt


def test_notfall_vertiefen_hat_plan_ohne_erfindung():
    text = vertiefen.notfall_vertiefen("Recall vereinbaren")
    assert "Recall vereinbaren" in text
    assert "Gesprächsplan" in text
    assert "nicht vorlesen" in text.lower() or "Regie" in text
    assert "erfinden" in text.lower()


def test_vertiefen_ohne_auftrag_scheitert():
    out = vertiefen.vertiefen("  ")
    assert not out["ok"] and out["auftrag"] == ""


def test_vertiefen_ohne_gedaechtnis_schreibt_trotzdem():
    from lisa import vorbereitung as vorb
    echt_g = vorb._gedaechtnis_stand
    echt_t = vorb._termine
    vorb._gedaechtnis_stand = lambda n, p: ([], "nichts")
    vorb._termine = lambda tid, pat: ([], [])
    try:
        out = vertiefen.vertiefen("Recall nächste Woche")
        assert out["ok"] and "Recall nächste Woche" in out["auftrag"]
        assert "Gesprächsplan" in out["briefing"]
        assert out["gedaechtnis"] == "nichts" and not out["hatStand"]
        assert not out["bereit"]
    finally:
        vorb._gedaechtnis_stand = echt_g
        vorb._termine = echt_t


def test_pizza_bleibt_pizza_kein_recall():
    assert vertiefen.bleibt_beim_thema("bestell eine pizza", "Pizza bestellen, Größe fragen.")
    assert not vertiefen.bleibt_beim_thema(
        "bestell eine pizza",
        "Zweck: Recall-Termin und PZR vereinbaren.",
    )
    text = vertiefen.notfall_vertiefen("bestell eine pizza")
    assert "pizza" in text.lower()
    assert vertiefen.bleibt_beim_thema("bestell eine pizza", text)
    assert not vertiefen._RECALL_RE.search(text)


def test_abwegiges_wird_nicht_dazuerfunden():
    from lisa import vorbereitung as vorb
    echt_g = vorb._gedaechtnis_stand
    echt_t = vorb._termine
    vorb._gedaechtnis_stand = lambda n, p: ([
        {"summary": "Zweck: Recall und professionelle Zahnreinigung.",
         "ts": 1, "status": "", "quelle": "kartei"},
    ], "ok")
    vorb._termine = lambda tid, pat: ([], [])
    try:
        out = vertiefen.vertiefen("bestell eine pizza")
        assert out["ok"] and "pizza" in out["auftrag"].lower()
        assert "recall" not in out["auftrag"].lower()
        assert "recall" not in " ".join(out["unterlage"]).lower()
    finally:
        vorb._gedaechtnis_stand = echt_g
        vorb._termine = echt_t


def test_lisa_prompt_fordert_gespraechstiefe():
    p = system_prompt(praxis="Testpraxis", behandler="Dr. T",
                      auftrag="Recall", patient="Anna Test")
    assert "GESPRÄCHSTIEFE" in p
    assert "nach Zug 2 nicht aufhören" in p
