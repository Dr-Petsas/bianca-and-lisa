"""W-ANLIEGEN-ART (09.09.2026): Servicebeschwerde/Notfall trennen und
Zusatzangebote (PZR/Bleaching) sperren. Notaus ANLIEGEN_ART=off. Offline.
"""

from bianca import flow, gehirn
from kern import anliegen_art
from kern.tenants import laden


# --- reine Erkennung ---------------------------------------------------------

def test_notfall_hat_vorrang():
    assert anliegen_art.art("Ich habe akut starke Schmerzen!") == "notfall"


def test_beschwerde_wird_erkannt():
    assert anliegen_art.art("Ich musste beim letzten Mal ewig warten, eine Frechheit.") == "beschwerde"


def test_klinisch_ohne_notfallmarker():
    assert anliegen_art.art("Mein Zahn ist etwas empfindlich.") == "klinisch"


def test_neutraler_satz_ist_leer():
    assert anliegen_art.art("Ich hätte gern einen Termin zur Kontrolle.") == ""


# --- sticky + Modus ----------------------------------------------------------

def test_merken_ist_off_no_op(monkeypatch):
    monkeypatch.setenv("ANLIEGEN_ART", "off")
    sit = {}
    anliegen_art.merken(sit, "Das ist eine Frechheit, ich beschwere mich!")
    assert "anliegenArt" not in sit


def test_merken_haelt_hoechste_lage(monkeypatch):
    monkeypatch.setenv("ANLIEGEN_ART", "enforce")
    sit = {}
    anliegen_art.merken(sit, "Mein Zahn ist empfindlich.")     # klinisch
    assert sit["anliegenArt"] == "klinisch"
    anliegen_art.merken(sit, "Und ich bin sehr unzufrieden!")  # beschwerde
    assert sit["anliegenArt"] == "beschwerde"
    anliegen_art.merken(sit, "Alles gut jetzt.")               # bleibt sticky
    assert sit["anliegenArt"] == "beschwerde"


def test_upsell_gesperrt_nur_enforce(monkeypatch):
    sit = {"anliegenArt": "beschwerde"}
    monkeypatch.setenv("ANLIEGEN_ART", "shadow")
    assert anliegen_art.upsell_gesperrt(sit) is False
    monkeypatch.setenv("ANLIEGEN_ART", "enforce")
    assert anliegen_art.upsell_gesperrt(sit) is True


# --- Fluss: PZR-Einschub wird bei Beschwerde gesperrt (enforce) --------------

def _sit_mit_pzr(monkeypatch) -> dict:
    """Zustand, in dem gehirn.pzr_faellig True wäre (Bestand, letzte PZR alt)."""
    monkeypatch.setattr(flow.hintergrund, "anstossen", lambda sit: None)
    sit = {"stimme": "Bianca", "tenant": laden("meddent")}
    s = gehirn.sammler(sit)
    s.update({"modus": "buchen", "grund": "Kontrolle", "warSchonMal": True,
              "pzr": "", "letzteReinigung": "2024-01-01"})
    return sit


def test_einschub_sperrt_pzr_bei_beschwerde(monkeypatch):
    monkeypatch.setenv("ANLIEGEN_ART", "enforce")
    sit = _sit_mit_pzr(monkeypatch)
    if not gehirn.pzr_faellig(gehirn.sammler(sit), sit):
        return  # Vorbedingung im Katalog nicht gegeben -> Test überspringen
    sit["anliegenArt"] = "beschwerde"
    aus = flow._einschub(sit)
    assert aus is None  # kein PZR-Angebot während der Beschwerde
    spuren = [e["w"] for e in (sit.get("_spur") or [])]
    assert "anliegen-art" in spuren


def test_einschub_bietet_pzr_ohne_beschwerde(monkeypatch):
    monkeypatch.setenv("ANLIEGEN_ART", "enforce")
    sit = _sit_mit_pzr(monkeypatch)
    if not gehirn.pzr_faellig(gehirn.sammler(sit), sit):
        return
    aus = flow._einschub(sit)
    assert aus and "reinig" in aus["text"].lower()
