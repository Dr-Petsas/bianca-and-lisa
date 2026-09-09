"""Blessing / Dermatologie: NIE Dental-Upselling (Regressions-Schloss).

Chef-Vorgabe: Zahnmedizinisches darf auf gar keinen Fall bei Blessing
(Hautarztpraxis Doktor Blessing, clientId UUJnPzoYPa4yYyzcaGlm) landen. Die
Unterdrueckung ist bereits KATALOG-getrieben (kein clientId-Sonderfall):

- ``gehirn.pzr_noch_fragen`` / ``pzr_faellig`` verlangen ``motive.fuehrt_pzr``
  (Katalog fuehrt eine Zahnreinigung) — eine Derma-Praxis fuehrt keine.
- ``gehirn.bleaching_faellig`` verlangt eine Aufhellung im Motiv-Katalog.

Dieser Test friert das Verhalten ein: selbst mit einem (fuer Derma
unsinnigen) dental gefaerbten Sammler bleiben die Zusatzangebote aus,
waehrend derselbe Sammler bei einem Zahn-Katalog feuert. So kann ein
spaeterer Umbau die Katalog-Wache nicht still zerbrechen.
"""

from bianca import gehirn
from kern import fachprofil, motive

KAT_DERMA = [
    {"id": "haut", "name": "Hautkrebsscreening"},
    {"id": "mutt", "name": "Muttermal-Kontrolle"},
    {"id": "akne", "name": "Akne-Sprechstunde"},
]
KAT_DENTAL = [
    {"id": "pzr", "name": "Professionelle Zahnreinigung (PZR)"},
    {"id": "bl", "name": "Bleaching / Zahnaufhellung"},
    {"id": "ko", "name": "Kontrolle"},
]


def _sit(kat: list[dict], **sammler) -> dict:
    s = {"modus": "buchen", "phase": "", "frage": ""}
    s.update(sammler)
    return {"tenant": {"visitMotives": kat}, "sammler": s, "messages": []}


# --- Katalog-Klassifikation --------------------------------------------------

def test_derma_katalog_ist_weder_zahn_noch_pzr():
    sit = _sit(KAT_DERMA)
    assert fachprofil.fach_id(sit) == "dermatologie"
    assert motive.ist_zahn(sit) is False
    assert motive.fuehrt_pzr(sit) is False
    # Gegenprobe: der Zahn-Katalog IST zahn und fuehrt PZR.
    dent = _sit(KAT_DENTAL)
    assert motive.ist_zahn(dent) is True
    assert motive.fuehrt_pzr(dent) is True


# --- PZR-Mitbuchen: nur bei Zahn-Katalog ------------------------------------

def test_pzr_gesperrt_bei_derma_aber_offen_bei_zahn():
    # Zustand, der bei einer Zahnpraxis die PZR-Frage ausloest.
    kwargs = dict(grund="Kontrolle", warSchonMal=True, pzr="")
    dent = _sit(KAT_DENTAL, **kwargs)
    assert gehirn.pzr_faellig(gehirn.sammler(dent), dent) is True
    # Exakt derselbe Sammler, aber Derma-Katalog -> nie.
    derma = _sit(KAT_DERMA, **kwargs)
    assert gehirn.pzr_faellig(gehirn.sammler(derma), derma) is False
    assert gehirn.pzr_noch_fragen(gehirn.sammler(derma), derma) is False


# --- Bleaching: nur bei Aufhellungs-Motiv im Katalog ------------------------

def test_bleaching_gesperrt_bei_derma_aber_offen_bei_zahn():
    kwargs = dict(grund="Zahnreinigung", wunsch={"tag": "morgen"},
                  bleaching="", phase="", frage="")
    dent = _sit(KAT_DENTAL, **kwargs)
    assert gehirn.bleaching_faellig(dent) is True
    derma = _sit(KAT_DERMA, **kwargs)
    assert gehirn.bleaching_faellig(derma) is False
