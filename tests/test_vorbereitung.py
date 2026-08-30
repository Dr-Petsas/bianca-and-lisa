"""Lisa-Sammelphase: nur Belegtes, Historie-Einwände, nichts erfinden."""

from __future__ import annotations

from lisa import vorbereitung as v
from lisa.prompt import system_prompt


def test_ohne_auftrag_scheitert():
    out = v.sammeln("  ")
    assert not out["ok"] and out["auftrag"] == "" and not out["bereit"]


def test_recall_ohne_historie_fragt_den_chef():
    echt_g = v._gedaechtnis_stand
    echt_t = v._termine
    v._gedaechtnis_stand = lambda n, p: ([], "nichts")
    v._termine = lambda tid, pat: ([], [])
    try:
        out = v.sammeln("Recall nächste Woche", patient={"name": "Anna Test"})
        assert out["ok"] and out["auftrag"] == "Recall nächste Woche"
        assert not out["bereit"]
        assert any("letzte Besuch" in x for x in out["luecken"])
        assert "Recall nächste Woche" in out["briefing"]
        assert "erfinden" in out["briefing"].lower()
    finally:
        v._gedaechtnis_stand = echt_g
        v._termine = echt_t


def test_kommender_termin_wird_einwand():
    echt_g = v._gedaechtnis_stand
    echt_t = v._termine
    v._gedaechtnis_stand = lambda n, p: ([], "nichts")
    v._termine = lambda tid, pat: ([], [
        {"label": "Dienstag 8.9. um 09:00", "iso": "2026-09-08T09:00:00", "date": "2026-09-08"},
    ])
    try:
        out = v.sammeln("Recall vereinbaren", patient={"name": "Anna Test"})
        assert out["bereit"]
        assert any("komme doch schon" in x for x in out["einwaende"])
        assert any("Dienstag 8.9" in x for x in out["unterlage"])
        assert "120" not in out["briefing"]
    finally:
        v._gedaechtnis_stand = echt_g
        v._termine = echt_t


def test_pizza_kein_recall_kein_termin_einwand():
    echt_g = v._gedaechtnis_stand
    echt_t = v._termine
    v._gedaechtnis_stand = lambda n, p: ([], "nichts")
    v._termine = lambda tid, pat: (
        [{"label": "Kontrolle letzte Woche", "iso": "2026-08-23T09:00:00", "date": "2026-08-23"}],
        [{"label": "Dienstag 8.9.", "iso": "2026-09-08T09:00:00", "date": "2026-09-08"}],
    )
    try:
        out = v.sammeln("bestell eine pizza", patient={"name": "Pizzeria Da Mario"})
        assert "pizza" in out["auftrag"].lower()
        assert not any("Recall" in x for x in out["einwaende"])
        assert not any("komme doch schon" in x for x in out["einwaende"])
        assert any("Unterlage" in x or "Mail" in x or "Vorgang" in x for x in out["luecken"])
    finally:
        v._gedaechtnis_stand = echt_g
        v._termine = echt_t


def test_mail_und_anruf_kommen_in_die_unterlage():
    echt_g = v._gedaechtnis_stand
    echt_t = v._termine
    v._gedaechtnis_stand = lambda n, p: ([
        {"summary": "Laut E-Mail (Nadine): Bestellung Labor 12er, Lieferung KW36.",
         "ts": 1767100000000, "status": "none", "quelle": "kartei"},
        {"summary": "Laut Anruf (Lisa): Labor nicht erreicht, Rückruf offen.",
         "ts": 1767200000000, "status": "open", "quelle": "suche"},
        {"summary": "Zollabfertigung AWB 123 Demo-Interessent",
         "ts": 1767000000000, "status": "none", "quelle": "kartei"},
    ], "ok")
    v._termine = lambda tid, pat: ([], [])
    try:
        out = v.sammeln("Labor wegen Bestellung anrufen", patient={"name": "Labor Nord"})
        text = " ".join(out["unterlage"]).lower()
        assert "bestellung labor" in text
        assert "nicht erreicht" in text
        assert "zoll" not in text and "awb" not in text
        assert out["hatStand"]
    finally:
        v._gedaechtnis_stand = echt_g
        v._termine = echt_t


def test_zahn_muell_nicht_bei_firma():
    ev = {"summary": "Laut Anruf: Recall-Termin und PZR vereinbaren.", "ts": 1, "status": ""}
    assert not v._filter_event(ev, "bestell eine pizza")
    assert v._filter_event(
        {"summary": "Laut E-Mail: Pizza-Bestellung vom Dienstag, extra Käse.",
         "ts": 1, "status": ""},
        "bestell eine pizza",
    )


def test_prompt_hat_unterlage_und_erfindet_nicht():
    p = system_prompt(
        praxis="Testpraxis", behandler="Dr. T", auftrag="Recall",
        patient="Anna Test", unterlage="Kartei, kommend: Dienstag 8.9.",
    )
    assert "UNTERLAGE" in p
    assert "nichts ergänzen" in p
    assert "ich war doch erst da" in p.lower()
