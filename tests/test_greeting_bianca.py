"""Bianca-Begruessung: Was (nicht Wem) kann ich fuer Sie tun."""

from bianca.greeting import begruessung, gruss_saeubern
from kern.tenants import laden


BLESSING_GRUSS = (
    "Hallo, Hautarztpraxis Doktor Blessing, Sie sprechen mit der Ka-ih "
    "Assistentin Bianca ...Wie kann ich helfen?"
)


def test_begruessung_fragt_was_nicht_wem():
    t = begruessung("Med Dent Zahnklinik")
    assert "Was kann ich für Sie tun?" in t
    assert "Wem kann ich" not in t


def test_gruss_saeubert_wem_zu_was():
    assert "Was kann ich" in gruss_saeubern(
        "Med Dent, guten Tag! Mein Name ist Bianca. Wem kann ich für Sie tun?"
    )


def test_blessing_meldet_sich_mit_dem_festgelegten_wortlaut():
    assert gruss_saeubern(laden("blessing")["begruessungText"]) == BLESSING_GRUSS
